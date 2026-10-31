"""Bounded, opt-in dual-channel server recording. Caller left, assistant right."""
import io
import time
import wave
from datetime import timedelta
import numpy as np
import soxr
from .db import session_scope,now
from .models import Recording
from .storage import get_store,put_checked


class AudioTimeline:
    def __init__(self,config):
        self.enabled=bool(config.get('recording',{}).get('enabled'))
        self.started=time.monotonic()
        self.limit=min(config.get('behavior',{}).get('max_connected_seconds',300),900)
        self.retention=min(max(config.get('recording',{}).get('retention_days',7),1),365)
        self.pieces=[]
        self.bytes=0

    def add(self,pcm,rate,channel):
        if not self.enabled or not pcm:return
        if self.bytes+len(pcm)>self.limit*96000:return
        stamp=max(0,time.monotonic()-self.started)
        if stamp>=self.limit:return
        self.pieces.append((stamp,rate,channel,bytes(pcm)));self.bytes+=len(pcm)

    def finish(self,workspace_id,call_id):
        if not self.enabled or not self.pieces:return
        count=min(int((time.monotonic()-self.started+.1)*16000),int(self.limit*16000))
        if count<=0:return
        output=np.zeros((count,2),dtype=np.int16)
        for stamp,rate,channel,body in self.pieces:
            samples=np.frombuffer(body,dtype='<i2')
            if rate!=16000:samples=soxr.resample(samples,rate,16000,quality='LQ').astype(np.int16)
            start=int(stamp*16000);length=min(len(samples),count-start)
            if length>0:output[start:start+length,channel]=samples[:length]
        stream=io.BytesIO()
        with wave.open(stream,'wb') as file:
            file.setnchannels(2);file.setsampwidth(2);file.setframerate(16000);file.writeframes(output.astype('<i2').tobytes())
        body=stream.getvalue();key=put_checked(workspace_id,'recordings',body,'audio/wav')
        with session_scope(write=True) as db:
            from .metering import stored
            stored(db,workspace_id,key,len(body))
            db.add(Recording(workspace_id=workspace_id,call_id=call_id,object_key=key,duration_ms=count//16,size_bytes=len(body),expires_at=now()+timedelta(days=self.retention)))
        self.pieces.clear()
