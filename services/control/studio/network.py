"""Public HTTP transport that validates and pins DNS at the actual TCP connection.

The original origin/SNI is retained by httpcore. Only the socket's destination is
replaced with the validated IP, closing the validation-to-connect rebinding gap.
"""
import asyncio
import ipaddress
import socket
import ssl
import httpcore
import httpx
from httpcore._backends.auto import AutoBackend


def configured_public_proxy():
    """An explicit proxy mode must never silently use a direct route."""
    import os
    from urllib.parse import urlparse
    from .config import settings
    value = settings.public_http_proxy or os.environ.get('HTTPS_PROXY') or os.environ.get('https_proxy') or os.environ.get('HTTP_PROXY') or os.environ.get('http_proxy') or ''
    try:
        parsed = urlparse(value)
        valid = parsed.scheme in {'http', 'https'} and parsed.hostname and parsed.port != 0
    except ValueError:
        valid = False
    if not valid:
        raise ValueError('Crawling is set to proxy mode, but no valid HTTP/HTTPS proxy is configured. For a normal local connection, set PUBLIC_NETWORK_MODE=direct and restart the API and worker. Otherwise configure PUBLIC_HTTP_PROXY.')
    return value


class PublicBackend(httpcore.AsyncNetworkBackend):
    def __init__(self,backend=None):self.backend=backend or AutoBackend()
    async def connect_tcp(self,host,port,timeout=None,local_address=None,socket_options=None):
        addresses=await asyncio.to_thread(socket.getaddrinfo,host,port,type=socket.SOCK_STREAM)
        if not addresses:raise httpcore.ConnectError('Destination has no public address')
        ips=list(dict.fromkeys(x[4][0] for x in addresses))
        if any((not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast) for ip in ips):raise httpcore.ConnectError('Non-public destination denied')
        last=None
        for ip in ips:
            try:return await self.backend.connect_tcp(ip,port,timeout,local_address,socket_options)
            except (httpcore.ConnectError,httpcore.ConnectTimeout) as exc:last=exc
        raise last or httpcore.ConnectError('Unable to connect')
    async def connect_unix_socket(self,*args,**kwargs):raise httpcore.ConnectError('Unix sockets are not allowed')
    async def sleep(self,seconds):await asyncio.sleep(seconds)


class PublicTransport(httpx.AsyncHTTPTransport):
    def __init__(self):
        super().__init__(trust_env=False,retries=0)
        # httpx 0.28/httpcore 1.0 integration; covered by socket-destination tests.
        from .config import settings
        backend = PublicProxyBackend() if settings.public_network_mode == 'proxy' else PublicBackend()
        self._pool=httpcore.AsyncConnectionPool(ssl_context=ssl.create_default_context(),network_backend=backend,max_connections=20,max_keepalive_connections=10,retries=0)


async def resolve_public_ips(host, port):
    """Resolve through the configured environment route, then reject any private IP.

    The HTTPS resolver is only used in explicitly enabled proxy mode, where the
    managed executor has no local external DNS. Its result is pinned in CONNECT;
    the proxy never gets an unvalidated target hostname to resolve again.
    """
    from .config import settings
    try:
        literal = ipaddress.ip_address(host)
    except ValueError:
        literal = None
    if literal is not None:
        ips = [str(literal)]
    elif settings.public_network_mode == 'proxy':
        import time
        proxy = configured_public_proxy()
        cached = _dns_cache.get(host)
        if cached and cached[0] > time.monotonic(): return list(cached[1])
        ips, ttl = [], 60
        async with httpx.AsyncClient(timeout=10, verify=ssl.create_default_context(), proxy=proxy) as client:
            for record_type in ('A', 'AAAA'):
                response = await client.get('https://cloudflare-dns.com/dns-query', params={'name':host, 'type':record_type}, headers={'Accept':'application/dns-json'})
                response.raise_for_status()
                result = response.json()
                if result.get('Status') != 0: raise httpcore.ConnectError('Public hostname resolution failed')
                for answer in result.get('Answer', []):
                    if answer.get('type') in (1,28):
                        ips.append(str(ipaddress.ip_address(answer['data'])))
                        ttl = min(ttl, max(0, int(answer.get('TTL', 0))))
        if not ips: raise httpcore.ConnectError('Destination has no public address')
        if any((not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast) for ip in ips): raise httpcore.ConnectError('Non-public destination denied')
        if len(_dns_cache) >= 1000: _dns_cache.clear()
        _dns_cache[host] = (time.monotonic() + ttl, tuple(dict.fromkeys(ips)))
    else:
        addresses = await asyncio.to_thread(socket.getaddrinfo,host,port,type=socket.SOCK_STREAM)
        ips = list(dict.fromkeys(x[4][0] for x in addresses))
    if not ips: raise httpcore.ConnectError('Destination has no public address')
    if any((not ipaddress.ip_address(ip).is_global or ipaddress.ip_address(ip).is_multicast) for ip in ips): raise httpcore.ConnectError('Non-public destination denied')
    return list(dict.fromkeys(ips))


_dns_cache = {}


class PublicProxyBackend(httpcore.AsyncNetworkBackend):
    """Tunnel a validated IP through the inherited HTTP proxy, retaining TLS/SNI.

    httpcore still owns the original origin and TLS hostname. Only socket opening
    changes: the standard CONNECT target is the already-validated public IP.
    """
    def __init__(self, backend=None):
        import os
        from urllib.parse import urlparse
        from .config import settings
        self.backend = backend or AutoBackend()
        self.proxy = urlparse(configured_public_proxy())

    async def connect_tcp(self, host, port, timeout=None, local_address=None, socket_options=None):
        import base64
        from urllib.parse import unquote
        if port not in (80,443): raise httpcore.ConnectError('Only public HTTP/HTTPS ports are allowed')
        ips = await resolve_public_ips(host, port)
        last = None
        for ip in ips:
            stream = None
            try:
                stream = await self.backend.connect_tcp(self.proxy.hostname, self.proxy.port or (443 if self.proxy.scheme=='https' else 80), timeout, local_address, socket_options)
                if self.proxy.scheme == 'https':
                    stream = await stream.start_tls(ssl.create_default_context(), server_hostname=self.proxy.hostname, timeout=timeout)
                target = ('['+ip+']' if ':' in ip else ip)+':'+str(port)
                headers = 'CONNECT '+target+' HTTP/1.1\r\nHost: '+target+'\r\n'
                if self.proxy.username:
                    auth = base64.b64encode((unquote(self.proxy.username)+':'+unquote(self.proxy.password or '')).encode()).decode()
                    headers += 'Proxy-Authorization: Basic '+auth+'\r\n'
                await stream.write((headers+'\r\n').encode('ascii'), timeout=timeout)
                response = b''
                while b'\r\n\r\n' not in response:
                    chunk = await stream.read(4096, timeout=timeout)
                    if not chunk or len(response)+len(chunk)>16384: raise httpcore.ProxyError('Invalid proxy CONNECT response')
                    response += chunk
                head, extra = response.split(b'\r\n\r\n',1)
                line = head.split(b'\r\n',1)[0].split(b' ',2)
                if len(line)<2 or not line[1].isdigit(): raise httpcore.ProxyError('Invalid proxy CONNECT status')
                status = int(line[1])
                if not 200<=status<300: raise httpcore.ProxyError('Proxy CONNECT rejected with status '+str(status))
                if extra: raise httpcore.ProxyError('Unexpected data after proxy CONNECT')
                return stream
            except httpcore.ProxyError:
                if stream: await stream.aclose()
                raise  # Never route around an explicit proxy policy denial.
            except (httpcore.ConnectError, httpcore.ConnectTimeout, httpcore.ReadError, httpcore.WriteError, httpcore.ReadTimeout, httpcore.WriteTimeout) as exc:
                if stream: await stream.aclose()
                last = exc
            except BaseException:
                if stream: await stream.aclose()
                raise
        raise last or httpcore.ConnectError('Unable to connect through configured proxy')

    async def connect_unix_socket(self,*args,**kwargs): raise httpcore.ConnectError('Unix sockets are not allowed')
    async def sleep(self,seconds): await asyncio.sleep(seconds)
