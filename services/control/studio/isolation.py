"""Application-side sandbox protocol; never fall back to in-process parsing."""
import asyncio
import base64
import json
from typing import Protocol

from .config import settings


class ContentSandbox(Protocol):
    async def run(self,request: dict,fetch=None) -> dict: ...


class UnixContentSandbox:
    async def run(self,request,fetch=None):
        writer=None
        pending=set()
        try:
            async with asyncio.timeout(settings.content_sandbox_timeout_seconds):
                reader,writer=await asyncio.open_unix_connection(settings.content_sandbox_socket,limit=32_000_001)
                writer.write(json.dumps(request,separators=(',',':')).encode()+b'\n');await writer.drain()
                while True:
                    line=await reader.readline()
                    if not line or len(line)>32_000_000:raise ValueError('Content sandbox disconnected')
                    result=json.loads(line)
                    if result.get('type')=='result':return result
                    if result.get('type')=='error':raise ValueError(result.get('error','Content rejected'))
                    if result.get('type')!='fetch' or fetch is None:raise ValueError('Invalid sandbox protocol')
                    async def answer(message):
                        response=await fetch(message)
                        writer.write(json.dumps(response,separators=(',',':')).encode()+b'\n');await writer.drain()
                    task=asyncio.create_task(answer(result));pending.add(task)
        except (OSError,TimeoutError) as error:
            raise ValueError('Content isolation service unavailable or timed out') from error
        finally:
            for task in pending:task.cancel()
            await asyncio.gather(*pending,return_exceptions=True)
            if writer:
                writer.close()
                try:await writer.wait_closed()
                except OSError:pass


provider: ContentSandbox=UnixContentSandbox()


async def parse_document(body,suffix):
    if not body or len(body)>20_000_000:raise ValueError('Document size limit exceeded')
    result=await provider.run({'operation':'parse','body':base64.b64encode(body).decode(),'suffix':suffix})
    text=result.get('text')
    if not isinstance(text,str) or len(text)>1_000_000 or len(text.strip())<12:raise ValueError('Invalid sandbox text result')
    return text


async def canonical_audio(body):
    """Only bounded decoder output is sent to transcription, never attacker media."""
    import io
    import wave
    if not body or len(body)>5_000_000:raise ValueError('Audio size limit exceeded')
    result=await provider.run({'operation':'audio','body':base64.b64encode(body).decode()})
    pcm=base64.b64decode(result['body'],validate=True)
    if not pcm or len(pcm)>960000 or len(pcm)%2:raise ValueError('Record up to 30 seconds at a time')
    buffer=io.BytesIO()
    with wave.open(buffer,'wb') as output:
        output.setnchannels(1);output.setsampwidth(2);output.setframerate(16000);output.writeframes(pcm)
    return buffer.getvalue(),len(pcm)//32


async def invoice_pdf(html):
    if not isinstance(html,str) or len(html.encode())>128000:raise ValueError('Invoice document exceeds limit')
    result=await provider.run({'operation':'invoice','html':html})
    body=base64.b64decode(result['body'],validate=True)
    if not body.startswith(b'%PDF') or len(body)>5_000_000:raise ValueError('Invalid invoice PDF result')
    return body
