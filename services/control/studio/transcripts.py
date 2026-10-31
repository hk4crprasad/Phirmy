"""Versioned transcript patches use Unicode code-point offsets, never byte offsets."""
from .db import uid


class Transcript:
    def __init__(self,send,speaker,epoch,*,identity=None,deltas=False):
        self.send,self.speaker,self.epoch=send,speaker,epoch
        self.identity=identity or uid()
        self.deltas=deltas
        self.previous=''
        self.sequence=0

    async def write(self,text,*,final=False):
        if not final and text==self.previous:return
        fields={'speaker':self.speaker,'turn_id':self.identity,'epoch':self.epoch}
        if final or not self.deltas:
            await self.send('server.transcript',text=text,final=final,**fields)
        else:
            retained=0
            if text.startswith(self.previous):retained=len(self.previous)
            else:
                for old,new in zip(self.previous,text):
                    if old!=new:break
                    retained+=1
            await self.send('server.transcript.delta',retain=retained,delta=text[retained:],seq=self.sequence,**fields)
            self.sequence+=1
        self.previous=text
