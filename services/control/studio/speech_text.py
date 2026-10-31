"""Bounded, streaming presentation-markup removal for speech, not business facts."""
import html
import re

from fishaudio.types import FlushEvent


def plain_text(text):
    text = re.sub(r'(?m)^[ \t]*```[^\n]*', '', text)
    text = re.sub(r'!?\[([^\]]*)\]\([^)]*\)', r'\1', text)
    text = re.sub(r'<[^>]*>', '', text)
    text = re.sub(r'(?m)^[ \t]{0,3}#{1,6}[ \t]*', '', text)
    text = re.sub(r'(?m)^[ \t]*(?:[-*+•–—][ \t]+|\d+[.)][ \t]+|>[ \t]*)', '', text)
    text = re.sub(r'(?m)^[ \t]*\|?[ \t]*:?-{3,}:?(?:[ \t]*\|[ \t]*:?-{3,}:?)*[ \t]*\|?[ \t]*$', '', text)
    text = text.replace('**', '').replace('__', '').replace('~~', '').replace('`', '')
    text = re.sub(r'(?<!\w)[*_](?=\S)|(?<=\S)[*_](?!\w)', '', text)
    text = text.replace('|', ', ')
    text = html.unescape(text)
    # Keep currency, decimal/grouping signs and native scripts unchanged. Never
    # submit standalone Markdown/punctuation tokens that the speech API rejects.
    return text if any(char.isalnum() for char in text) else ''


async def speech_chunks(texts):
    buffer = ''
    async for part in texts:
        if isinstance(part, FlushEvent):
            spoken = plain_text(buffer)
            buffer = ''
            if spoken:
                yield spoken
            yield part
            continue
        buffer += part
        while buffer:
            boundary = re.search(r'\n+|(?<=[.!?।])\s+', buffer)
            cut = boundary.end() if boundary else 0
            if not cut and len(buffer) >= 40:
                cut = buffer.rfind(' ', 0, 161) + 1
                # Wait for a complete link/tag rather than speaking its syntax.
                prefix = buffer[:cut]
                if prefix.count('[') > prefix.count(']') or prefix.rfind('<') > prefix.rfind('>'):
                    cut = 0
            if not cut and len(buffer) >= 1024:
                cut = 1024  # Bounded even for malformed markup/unbroken text.
            if not cut:
                break
            piece, buffer = buffer[:cut], buffer[cut:]
            spoken = plain_text(piece)
            if spoken:
                yield spoken
                if boundary:
                    yield FlushEvent()
    spoken = plain_text(buffer)
    if spoken:
        yield spoken
    yield FlushEvent()
