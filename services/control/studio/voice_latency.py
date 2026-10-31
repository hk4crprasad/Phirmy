"""Monotonic voice timings without prompts, transcripts or provider credentials."""
from contextlib import contextmanager
from contextvars import ContextVar
import math
import time

from sqlalchemy import select

from .db import as_dict, session_scope, uid

current = ContextVar('voice_latency', default=None)


class Trace:
    def __init__(self, workspace_id, call_id, epoch, source, input_kind, *, started_at=None, clock=time.monotonic):
        self.workspace_id, self.call_id, self.epoch = workspace_id, call_id, epoch
        self.source, self.input_kind, self.clock = source, input_kind, clock
        self.turn_id = uid()
        self.started_at = clock() if started_at is None else started_at
        self.marks = {'input_received':0.0}
        if input_kind == 'stt_final':
            self.marks['stt_final'] = 0.0
        self.spans = {}
        self.status = 'running'

    def mark(self, name):
        if name not in self.marks:
            self.marks[name] = round(max(0,self.clock()-self.started_at)*1000,3)

    @contextmanager
    def measure(self, name):
        started = self.clock()
        self.mark(name+'_started')
        try:
            yield
        finally:
            self.spans[name] = round(self.spans.get(name,0)+max(0,self.clock()-started)*1000,3)
            self.mark(name+'_complete')

    def finish(self, status):
        self.status = status
        self.mark('response_finished')

    def values(self):
        def elapsed(start, end):
            return round(self.marks[end]-self.marks[start],3) if start in self.marks and end in self.marks else None
        return {'final_transcript_to_first_audio_ms':elapsed('stt_final','first_audio_sent'),
            'input_to_first_audio_ms':elapsed('input_received','first_audio_sent'),
            'turn_admission_ms':self.spans.get('turn_admission'),
            'safety_ms':self.spans.get('safety'),
            'retrieval_ms':self.spans.get('retrieval'),
            'retrieval_prefetch_ms':self.spans.get('retrieval_prefetch'),
            'llm_admission_ms':self.spans.get('llm_admission'),
            'tts_admission_ms':self.spans.get('tts_admission'),
            'llm_first_token_ms':elapsed('llm_request_started','llm_first_token'),
            'tts_connect_ms':self.spans.get('tts_connect',elapsed('tts_setup_started','tts_connected')),
            'tts_first_byte_ms':elapsed('tts_first_text_sent','first_tts_byte'),
            'tts_byte_to_audio_sent_ms':elapsed('first_tts_byte','first_audio_sent')}


def mark(name):
    trace = current.get()
    if trace is not None:
        trace.mark(name)


@contextmanager
def measure(name):
    trace = current.get()
    if trace is None:
        yield
    else:
        with trace.measure(name):
            yield


def persist(trace):
    from .models import Call, VoiceTimingRecord
    with session_scope(write=True) as db:
        call = db.scalar(select(Call.id).where(Call.id==trace.call_id,Call.workspace_id==trace.workspace_id))
        if call is None:
            return False
        if db.scalar(select(VoiceTimingRecord.id).where(VoiceTimingRecord.turn_id==trace.turn_id)):
            return True
        db.add(VoiceTimingRecord(workspace_id=trace.workspace_id,call_id=trace.call_id,turn_id=trace.turn_id,
            epoch=trace.epoch,source=trace.source,input_kind=trace.input_kind,status=trace.status,
            marks_ms=trace.marks,durations_ms=trace.values()))
    return True


def percentile(values, fraction):
    ordered = sorted(values)
    return ordered[max(0,math.ceil(len(ordered)*fraction)-1)] if ordered else None


def detail(db, workspace_id, call_id):
    from .models import VoiceTimingRecord
    rows = list(db.scalars(select(VoiceTimingRecord).where(VoiceTimingRecord.workspace_id==workspace_id,
        VoiceTimingRecord.call_id==call_id).order_by(VoiceTimingRecord.created_at.desc(),VoiceTimingRecord.id.desc()).limit(50)))
    summaries = []
    for source in sorted({row.source for row in rows}):
        stt_rows = [row for row in rows if row.source==source and row.input_kind=='stt_final']
        values = [row.durations_ms['final_transcript_to_first_audio_ms'] for row in stt_rows
            if row.status=='completed' and row.durations_ms.get('final_transcript_to_first_audio_ms') is not None]
        summaries.append({'source':source,'stt_turns':len(stt_rows),'completed_stt_turns':len(values),
            'failed_stt_turns':sum(row.status in {'failed','denied','incomplete'} for row in stt_rows),
            'interrupted_stt_turns':sum(row.status=='interrupted' for row in stt_rows),
            'final_transcript_to_first_audio_p50_ms':percentile(values,.5),
            'final_transcript_to_first_audio_p95_ms':percentile(values,.95)})
    return {'basis':'Server receipt of final transcript to first audio transport write; not speaker playback or speech endpoint detection.',
        'sample_limit':50,'summaries':summaries,'items':[as_dict(row) for row in reversed(rows)]}
