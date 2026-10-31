from types import SimpleNamespace
from unittest.mock import AsyncMock
import ssl
import httpcore
import httpx
import pytest
from studio import network,knowledge
from studio.config import settings


class Stream:
    def __init__(self,status=200): self.status=status;self.writes=[];self.pending=b'';self.closed=False;self.tls=[]
    async def write(self,data,timeout=None):
        self.writes.append(data)
        if data.startswith(b'CONNECT '): self.pending=b'HTTP/1.1 '+str(self.status).encode()+b' Result\r\n\r\n'
        else: self.pending=b'HTTP/1.1 200 OK\r\nContent-Length: 8\r\n\r\nevidence'
    async def read(self,max_bytes,timeout=None):
        data,self.pending=self.pending[:max_bytes],self.pending[max_bytes:];return data
    async def aclose(self): self.closed=True
    async def start_tls(self,ssl_context,server_hostname=None,timeout=None):
        assert ssl_context.verify_mode==ssl.CERT_REQUIRED and ssl_context.check_hostname
        self.tls.append(server_hostname);return self
    def get_extra_info(self,info): return None


@pytest.mark.asyncio
async def test_proxy_pins_ip_preserves_host_tls_and_separates_origins(monkeypatch):
    monkeypatch.setattr(settings,'public_network_mode','proxy')
    monkeypatch.setattr(settings,'public_http_proxy','http://proxy.fixture:8080')
    streams=[]
    async def connect(host,port,*args):
        assert (host,port)==('proxy.fixture',8080)
        stream=Stream();streams.append(stream);return stream
    monkeypatch.setattr(network,'AutoBackend',lambda:SimpleNamespace(connect_tcp=connect))
    resolver=AsyncMock(return_value=['8.8.8.8'])
    monkeypatch.setattr(network,'resolve_public_ips',resolver)
    async with httpx.AsyncClient(transport=network.PublicTransport()) as client:
        for host in ('one.example','two.example'):
            response=await client.get('https://'+host+'/page')
            assert response.text=='evidence'
    assert len(streams)==2
    for stream,host in zip(streams,('one.example','two.example')):
        assert stream.writes[0].startswith(b'CONNECT 8.8.8.8:443 HTTP/1.1')
        assert ('Host: '+host).lower().encode() in b''.join(stream.writes[1:]).lower()
        assert stream.tls==[host] and stream.closed


@pytest.mark.asyncio
async def test_proxy_denial_closes_socket_and_never_tries_another_route(monkeypatch):
    monkeypatch.setattr(settings,'public_http_proxy','http://proxy.fixture:8080')
    monkeypatch.setattr(network,'resolve_public_ips',AsyncMock(return_value=['8.8.8.8','1.1.1.1']))
    stream=Stream(status=403);backend=SimpleNamespace(connect_tcp=AsyncMock(return_value=stream))
    with pytest.raises(httpcore.ProxyError,match='403'):
        await network.PublicProxyBackend(backend).connect_tcp('one.example',443)
    assert stream.closed and backend.connect_tcp.await_count==1


@pytest.mark.asyncio
async def test_proxy_dns_rejects_mixed_public_private_answers(monkeypatch):
    monkeypatch.setattr(settings,'public_network_mode','proxy')
    monkeypatch.setattr(settings,'public_http_proxy','http://proxy.fixture:8080')
    network._dns_cache.clear()
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
        async def get(self,url,**kwargs):
            assert url=='https://cloudflare-dns.com/dns-query'
            answer=[{'type':1,'data':'8.8.8.8','TTL':60},{'type':1,'data':'127.0.0.1','TTL':60}]
            return httpx.Response(200,json={'Status':0,'Answer':answer},request=httpx.Request('GET',url))
    monkeypatch.setattr(network.httpx,'AsyncClient',lambda **kwargs:Client())
    with pytest.raises(httpcore.ConnectError,match='Non-public'):
        await network.resolve_public_ips('mixed.example',443)
    assert 'mixed.example' not in network._dns_cache


@pytest.mark.asyncio
@pytest.mark.parametrize('url',['https://127.0.0.1/','https://169.254.169.254/','https://[::1]/','https://224.0.0.1/','https://[ff00::1]/'])
async def test_proxy_mode_never_accepts_private_literal_url(monkeypatch,url):
    monkeypatch.setattr(settings,'public_network_mode','proxy')
    with pytest.raises(ValueError,match='public address'):
        await knowledge.validate_public_url(url)


@pytest.mark.asyncio
async def test_missing_proxy_is_actionable_and_never_uses_direct_dns_or_http(monkeypatch):
    monkeypatch.setattr(settings, 'public_network_mode', 'proxy')
    monkeypatch.setattr(settings, 'public_http_proxy', '')
    for key in ('HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy'):
        monkeypatch.delenv(key, raising=False)
    dns=AsyncMock(side_effect=AssertionError('Must not resolve directly'))
    monkeypatch.setattr(network.socket,'getaddrinfo',dns)
    monkeypatch.setattr(network.httpx,'AsyncClient',lambda **kwargs:pytest.fail('Must not send HTTP without the required proxy'))
    with pytest.raises(ValueError,match='PUBLIC_NETWORK_MODE=direct'):
        await network.resolve_public_ips('public.example',443)
    with pytest.raises(ValueError,match='restart the API and worker'):
        network.PublicProxyBackend()
    with pytest.raises(ValueError,match='PUBLIC_HTTP_PROXY'):
        await knowledge.validate_public_url('https://public.example/')


def test_proxy_error_does_not_echo_credentials(monkeypatch):
    monkeypatch.setattr(settings,'public_http_proxy','socks5://private-user:private-password@proxy.fixture:1080')
    with pytest.raises(ValueError) as error:network.configured_public_proxy()
    assert 'private-password' not in str(error.value)


@pytest.mark.asyncio
async def test_direct_mode_pins_public_dns_without_a_proxy(monkeypatch):
    monkeypatch.setattr(settings,'public_network_mode','direct')
    monkeypatch.setattr(settings,'public_http_proxy','')
    for key in ('HTTPS_PROXY','https_proxy','HTTP_PROXY','http_proxy'):
        monkeypatch.delenv(key,raising=False)
    monkeypatch.setattr(network.socket,'getaddrinfo',lambda *args,**kwargs:[(2,1,6,'',('8.8.8.8',443))])
    stream=Stream();backend=SimpleNamespace(connect_tcp=AsyncMock(return_value=stream))
    monkeypatch.setattr(network,'AutoBackend',lambda:backend)
    async with httpx.AsyncClient(transport=network.PublicTransport()) as client:
        response=await client.get('https://public.example/page')
    assert response.status_code==200 and response.text=='evidence'
    assert backend.connect_tcp.call_args.args[:2]==('8.8.8.8',443)
    assert not any(write.startswith(b'CONNECT ') for write in stream.writes)
    assert stream.tls==['public.example']
