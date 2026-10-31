"""Bounded streaming tool state. Only a completed response may authorize tools."""
from dataclasses import dataclass


def value(item, name, default=None):
    return item.get(name,default) if isinstance(item,dict) else getattr(item,name,default)


@dataclass(frozen=True)
class ToolCallStarted:
    item_id: str


class ModelIncompleteError(RuntimeError):
    def __init__(self, reason):
        self.reason=reason if reason in {'max_output_tokens','content_filter'} else 'unknown'
        super().__init__('The model response is incomplete: '+self.reason)


class ToolStreamState:
    def __init__(self):
        self.items={}

    def added(self, item):
        if value(item,'type')!='function_call':return None
        identity=value(item,'id')
        if not isinstance(identity,str) or not identity or len(identity)>256 or identity in self.items or len(self.items)>=8:
            raise RuntimeError('Invalid or excessive streamed tool items')
        name,call_id,args=value(item,'name'),value(item,'call_id'),value(item,'arguments','')
        if not isinstance(name,str) or not 1<=len(name)<=160 or not isinstance(call_id,str) or not 1<=len(call_id)<=256 or not isinstance(args,str):
            raise RuntimeError('Invalid streamed tool identity')
        if len(args.encode())>65536:raise RuntimeError('Streamed tool arguments exceeded their bound')
        self.items[identity]={'name':name,'id':call_id,'arguments':args,'done':False}
        return ToolCallStarted(identity)

    def arguments(self, event, done=False):
        item=self.items.get(value(event,'item_id'))
        if item is None or item['done']:raise RuntimeError('Tool arguments arrived without an active item')
        text=value(event,'arguments' if done else 'delta')
        if not isinstance(text,str):raise RuntimeError('Invalid streamed tool arguments')
        candidate=text if done else item['arguments']+text
        if len(candidate.encode())>65536:raise RuntimeError('Streamed tool arguments exceeded their bound')
        if done and item['arguments'] and candidate!=item['arguments']:
            raise RuntimeError('Final tool arguments changed their streamed value')
        item['arguments']=candidate
        item['done']=done

    def completed(self, output):
        calls=[]
        for item in output:
            if value(item,'type')!='function_call':continue
            call={'id':value(item,'call_id'),'name':value(item,'name'),'arguments':value(item,'arguments')}
            if any(not isinstance(call[key],str) or not call[key] for key in ('id','name')) or not isinstance(call['arguments'],str):
                raise RuntimeError('Invalid completed tool call')
            if len(call['id'])>256 or len(call['name'])>160 or len(call['arguments'].encode())>65536 or len(calls)>=8:
                raise RuntimeError('Completed tool call exceeded its bounds')
            streamed=self.items.get(value(item,'id'))
            if streamed and (not streamed['done'] or any(streamed[key]!=call[key] for key in call)):
                raise RuntimeError('Completed tool call differs from its streamed arguments')
            calls.append(call)
        if self.items:
            completed_ids={value(item,'id') for item in output if value(item,'type')=='function_call'}
            if set(self.items)!=completed_ids:
                raise RuntimeError('Completed response omitted streamed tool calls')
        if len({call['id'] for call in calls})!=len(calls):
            raise RuntimeError('Completed response repeated a tool identity')
        return calls
