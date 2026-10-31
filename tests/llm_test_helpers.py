"""SDK-boundary fakes: real request formatting, admission and usage code still run."""
from types import SimpleNamespace as NS


def profile(**overrides):
    return {'api_key':'synthetic-key','model':'gpt-5.6-luna','base_url':'https://api.openai.com/v1',
            'api_style':'responses','token_parameter':'max_output_tokens','options':{},**overrides}


def usage(**details):
    return NS(input_tokens=100,output_tokens=5,
              input_tokens_details=NS(**{'cached_tokens':10,'cache_write_tokens':0,**details}))


def completed(output=None, reported=None):
    return NS(type='response.completed',response=NS(output=output or [],usage=reported or usage()))


def install_sdk(monkeypatch, events):
    import openai
    requests=[]
    class Stream:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        def __aiter__(self):return self.iterate()
        async def iterate(self):
            for event in events:yield event
    class Client:
        def __init__(self,**kwargs):
            self.responses=NS(create=self.create)
            self.chat=NS(completions=NS(create=self.create))
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def create(self,**kwargs):
            requests.append(kwargs)
            return Stream()
    monkeypatch.setattr(openai,'AsyncOpenAI',Client)
    return requests
