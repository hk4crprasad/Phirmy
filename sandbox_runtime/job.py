"""Single-use untrusted-content process. Never import application configuration."""
import asyncio
import base64
import io
import json
import os
from pathlib import PurePosixPath
import resource
import sys
import zipfile

MAX_INPUT=20_000_000
MAX_TEXT=1_000_000
MAX_PAGES=200
MAX_EXPANDED=40_000_000
MAX_MEMBER=8_000_000


def send(value):
    sys.stdout.write(json.dumps(value,separators=(',',':'))+'\n');sys.stdout.flush()


def parse_document(body,suffix):
    if not body or len(body)>MAX_INPUT:raise ValueError('Document size limit exceeded')
    if suffix=='.pdf':
        from pypdf import PdfReader, overwrite_configuration, filters
        overwrite_configuration(maximum_declared_stream_length=5_000_000,
            array_based_stream_maximum_output_length=5_000_000,zlib_maximum_output_length=5_000_000,
            lzw_maximum_output_length=5_000_000,run_length_maximum_output_length=5_000_000,
            brotli_maximum_output_length=5_000_000,jbig2_maximum_output_length=5_000_000,
            image_maximum_buffer_size=5_000_000,stream_decoding_work_maximum_length=10_000_000,
            stream_parsing_work_maximum_count=200_000,page_tree_maximum_entries=1000,
            page_tree_maximum_depth=30,array_maximum_element_count=10000,
            dictionary_maximum_element_count=10000,xform_maximum_invocations_per_extraction=100,
            jbig2dec_binary=None)
        # Account across every decoded stream, not just the final extracted text.
        original=filters.decode_stream_data;expanded=0
        def bounded(stream):
            nonlocal expanded
            result=original(stream);expanded+=len(result)
            if expanded>MAX_EXPANDED:raise ValueError('PDF decompression budget exceeded')
            return result
        filters.decode_stream_data=bounded
        try:
            reader=PdfReader(io.BytesIO(body))
            if reader.is_encrypted:raise ValueError('Encrypted PDFs are not supported')
            if len(reader.pages)>MAX_PAGES:raise ValueError('PDF limit is 200 pages')
            parts=[];length=0
            for index,page in enumerate(reader.pages):
                # Explicitly bound content before text extraction allocates operators.
                content=page.get_contents()
                if content is not None and len(content.get_data())>5_000_000:
                    raise ValueError('PDF page content exceeds decompression limit')
                part=f'Page {index+1}\n'+(page.extract_text() or '')
                length+=len(part)
                if length>MAX_TEXT:raise ValueError('Extracted text limit exceeded')
                parts.append(part)
            text='\n\n'.join(parts)
        finally:filters.decode_stream_data=original
    elif suffix=='.docx':
        from lxml import etree
        with zipfile.ZipFile(io.BytesIO(body)) as archive:
            members=archive.infolist();names=set();expanded=0;parts={}
            if len(members)>1000:raise ValueError('DOCX entry limit exceeded')
            for info in members:
                path=PurePosixPath(info.filename)
                if (path.is_absolute() or '..' in path.parts or '\\' in info.filename
                    or info.filename in names or info.flag_bits & 1
                    or (info.external_attr>>16)&0o170000==0o120000):
                    raise ValueError('Unsafe DOCX package entry')
                names.add(info.filename);expanded+=info.file_size
                if info.file_size>MAX_MEMBER or expanded>MAX_EXPANDED:
                    raise ValueError('DOCX decompression budget exceeded')
                if info.file_size>max(100_000,info.compress_size*200):
                    raise ValueError('DOCX compression ratio limit exceeded')
                # Read every member through a bounded stream. Metadata alone is untrusted.
                with archive.open(info) as source:
                    data=source.read(MAX_MEMBER+1)
                    if len(data)>MAX_MEMBER or len(data)!=info.file_size:
                        raise ValueError('DOCX expanded member limit exceeded')
                if info.filename in {'word/document.xml','docProps/app.xml'}:parts[info.filename]=data
            if 'word/document.xml' not in parts:raise ValueError('Missing DOCX document')
            def xml(data):
                document=etree.fromstring(data,parser=etree.XMLParser(resolve_entities=False,
                    no_network=True,load_dtd=False,huge_tree=False))
                if document.getroottree().docinfo.doctype:raise ValueError('DOCX DTDs are prohibited')
                if sum(1 for _ in document.iter())>100_000:raise ValueError('DOCX XML node limit exceeded')
                return document
            root=xml(parts['word/document.xml']);ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
            breaks=len(root.xpath('//w:br[@w:type="page"] | //w:lastRenderedPageBreak',namespaces=ns))
            reported=0
            if 'docProps/app.xml' in parts:
                props=xml(parts['docProps/app.xml'])
                for element in props.iter():
                    if etree.QName(element).localname=='Pages':
                        try:reported=int(element.text or 0)
                        except ValueError:raise ValueError('Invalid DOCX page metadata')
            text='\n'.join(''.join(p.itertext()) for p in root.xpath('//w:p',namespaces=ns))
            # OOXML has no authoritative pagination. Bound declared/explicit pages
            # and an independent conservative 400-word/page content budget.
            estimated=(len(text.split())+399)//400
            if max(reported,breaks+1,estimated)>MAX_PAGES:raise ValueError('DOCX limit is 200 pages')
    elif suffix=='.txt':text=body.decode('utf-8-sig')
    else:raise ValueError('Unsupported document type')
    if len(text)>MAX_TEXT:raise ValueError('Extracted text limit exceeded')
    if len(text.strip())<12:raise ValueError('No usable text extracted; scanned PDFs need OCR')
    return text


async def render(request,exchange=None):
    from playwright.async_api import async_playwright, Error
    import shutil
    rpc_lock=asyncio.Lock();handlers=set();closing=False;page=None
    async def rpc(value):
        async with rpc_lock:
            send(value)
            line=await asyncio.to_thread(sys.stdin.buffer.readline,32_000_001)
            if not line or len(line)>32_000_000:raise ValueError('Fetch channel closed')
            return json.loads(line)
    if exchange is None:exchange=rpc
    else:
        injected=exchange
        async def serial(value):
            async with rpc_lock:return await injected(value)
        exchange=serial
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True,executable_path=shutil.which('chromium'),
            proxy={'server':'http://127.0.0.1:9','bypass':''},
            args=['--disable-dev-shm-usage','--disable-quic','--disable-background-networking',
                  '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
        context=None
        def target_closed(error):
            return not browser.is_connected() or (page is not None and page.is_closed()) or 'Target page, context or browser has been closed' in str(error)
        async def route_request(route):
            task=asyncio.current_task();handlers.add(task)
            try:
                if closing:await route.abort();return
                result=await exchange({'type':'fetch','url':route.request.url,
                    'method':route.request.method,'resource_type':route.request.resource_type})
                if closing or result.get('type')!='fetched':await route.abort();return
                body=base64.b64decode(result['body'],validate=True)
                if len(body)>5_000_000:raise ValueError('Rendered resource exceeds limit')
                await route.fulfill(status=200,content_type=result['mime'],body=body,
                    headers={'Content-Security-Policy':"connect-src 'self'; form-action 'none'; frame-src 'none'; object-src 'none'"})
            except Error as error:
                if closing or target_closed(error):raise asyncio.CancelledError() from error
                raise
            finally:handlers.discard(task)
        async def route_socket(socket):
            task=asyncio.current_task();handlers.add(task)
            try:await socket.close()
            except Error as error:
                if closing or target_closed(error):raise asyncio.CancelledError() from error
                raise
            finally:handlers.discard(task)
        try:
            context=await browser.new_context(service_workers='block',accept_downloads=False,
                user_agent=request['user_agent'])
            await context.add_init_script("""for (const key of ['RTCPeerConnection','webkitRTCPeerConnection','WebTransport','Worker','SharedWorker']) {
                Object.defineProperty(globalThis,key,{value:undefined,writable:false,configurable:false});
            }""")
            await context.route('**/*',route_request);await context.route_web_socket('**/*',route_socket)
            page=await context.new_page()
            await page.goto(request['url'],wait_until='domcontentloaded',timeout=20000)
            await page.wait_for_timeout(min(1500,max(0,request.get('settle_ms',1500))))
            html=(await page.content()).encode()
            if len(html)>5_000_000:raise ValueError('Rendered HTML exceeds limit')
            return html
        finally:
            closing=True
            try:
                if context:
                    try:await context.unroute_all(behavior='ignoreErrors')
                    except Error as error:
                        if not target_closed(error):raise
                pending=list(handlers)
                for task in pending:task.cancel()
                await asyncio.gather(*pending,return_exceptions=True)
                if context:await context.close()
            finally:await browser.close()


async def invoice_pdf(request):
    from playwright.async_api import async_playwright
    import shutil
    html=request.get('html')
    if not isinstance(html,str) or len(html.encode())>128000:raise ValueError('Invoice document exceeds limit')
    async with async_playwright() as playwright:
        browser=await playwright.chromium.launch(headless=True,executable_path=shutil.which('chromium'),
            proxy={'server':'http://127.0.0.1:9','bypass':''},
            args=['--disable-dev-shm-usage','--disable-quic','--disable-background-networking'])
        try:
            context=await browser.new_context(java_script_enabled=False,service_workers='block',accept_downloads=False)
            await context.route('**/*',lambda route:route.abort())
            page=await context.new_page()
            await page.set_content(html,wait_until='load',timeout=8000)
            body=await page.pdf(format='A4',print_background=True,margin={'top':'18mm','bottom':'18mm','left':'16mm','right':'16mm'})
            if len(body)>5_000_000:raise ValueError('Invoice PDF exceeds limit')
            return body
        finally:await browser.close()


async def main():
    resource.setrlimit(resource.RLIMIT_CORE,(0,0))
    resource.setrlimit(resource.RLIMIT_FSIZE,(64_000_000,64_000_000))
    resource.setrlimit(resource.RLIMIT_NOFILE,(256,256))
    resource.setrlimit(resource.RLIMIT_CPU,(20,21))
    request=json.loads(sys.stdin.buffer.readline(32_000_001))
    if request['operation']=='parse':
        resource.setrlimit(resource.RLIMIT_AS,(512*1024**2,512*1024**2))
        body=base64.b64decode(request['body'],validate=True)
        send({'type':'result','text':parse_document(body,request['suffix'])})
    elif request['operation']=='render':
        html=await asyncio.wait_for(render(request),30)
        send({'type':'result','body':base64.b64encode(html).decode()})
    elif request['operation']=='invoice':
        body=await asyncio.wait_for(invoice_pdf(request),12)
        send({'type':'result','body':base64.b64encode(body).decode()})
    elif request['operation']=='audio':
        import subprocess
        resource.setrlimit(resource.RLIMIT_AS,(512*1024**2,512*1024**2))
        resource.setrlimit(resource.RLIMIT_STACK,(1024**2,1024**2))
        body=base64.b64decode(request['body'],validate=True)
        if not body or len(body)>5_000_000:raise ValueError('Audio size limit exceeded')
        decoded=subprocess.run(['ffmpeg','-v','error','-cpucount','1','-threads','1','-filter_threads','1','-protocol_whitelist','pipe','-i','pipe:0',
            '-vn','-sn','-dn','-ac','1','-ar','16000','-threads','1','-f','s16le','-t','31','pipe:1'],
            # Native dependencies can size their own pools from the host CPU count,
            # independently of FFmpeg's decoder flag and container CPU quota.
            env={**os.environ,'OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1','MKL_NUM_THREADS':'1','MALLOC_ARENA_MAX':'2'},
            input=body,stdout=subprocess.PIPE,stderr=subprocess.DEVNULL,timeout=10)
        pcm=decoded.stdout
        if decoded.returncode or not pcm:raise ValueError('Invalid audio recording')
        if len(pcm)>30*32000:raise ValueError('Record up to 30 seconds at a time')
        send({'type':'result','body':base64.b64encode(pcm).decode()})
    elif request['operation']=='probe':
        import socket
        connected=False
        broker_access=False
        try:
            with socket.socket(socket.AF_UNIX) as connection:connection.connect('/socket/content.sock');broker_access=True
        except OSError:pass
        try:
            with socket.create_connection(('1.1.1.1',443),timeout=.2):connected=True
        except OSError:pass
        send({'type':'result','uid':os.getuid(),'network_available':connected,'broker_socket_access':broker_access,
              'app_files_visible':os.path.exists('/app/.env') or os.path.exists('/workspace'),
              'credential_names_present':any(name in os.environ for name in ['APP_SECRET','DATABASE_URL','OPENAI_API_KEY']),
              'memory_limit':open('/sys/fs/cgroup/memory.max').read().strip(),
              'pids_limit':open('/sys/fs/cgroup/pids.max').read().strip(),
              'cpu_limit':open('/sys/fs/cgroup/cpu.max').read().strip(),
              'capabilities':next(line.split(':',1)[1].strip() for line in open('/proc/self/status') if line.startswith('CapEff:')),
              'no_new_privileges':next(line.split(':',1)[1].strip() for line in open('/proc/self/status') if line.startswith('NoNewPrivs:'))})
    else:raise ValueError('Unsupported operation')


if __name__=='__main__':
    try:asyncio.run(main())
    except BaseException as error:
        # Error text can contain untrusted file content. Return a bounded category only.
        known=isinstance(error,ValueError) and type(error) is ValueError
        send({'type':'error','error':str(error)[:180] if known else 'Sandbox content rejected ('+type(error).__name__+')'})
        sys.exit(1)
