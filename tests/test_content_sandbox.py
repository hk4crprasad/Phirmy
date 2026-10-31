import asyncio
import io
import zipfile
from urllib.robotparser import RobotFileParser

import pytest

from studio import isolation,knowledge,website_extraction
from studio.config import settings


def docx(text='Useful documented business hours and service information.',extra=None):
    body=io.BytesIO()
    with zipfile.ZipFile(body,'w',zipfile.ZIP_DEFLATED) as archive:
        archive.writestr('word/document.xml',
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>'+text+'</w:t></w:r></w:p></w:body></w:document>')
        for name,value in (extra or {}).items():archive.writestr(name,value)
    return body.getvalue()


def pdf(pages=1,content=None):
    from pypdf import PdfWriter
    from pypdf.generic import DecodedStreamObject,DictionaryObject,NameObject
    writer=PdfWriter()
    for _ in range(pages):
        page=writer.add_blank_page(width=612,height=792)
        if content is not None:
            font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
            page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
            stream=DecodedStreamObject();stream.set_data(content)
            page[NameObject('/Contents')]=writer._add_object(stream.flate_encode())
    body=io.BytesIO();writer.write(body);return body.getvalue()


@pytest.mark.asyncio
@pytest.mark.sandbox
async def test_actual_container_has_no_credentials_app_files_network_or_privileges():
    result=await isolation.provider.run({'operation':'probe'})
    assert result['uid']!=0 and result['network_available'] is False
    assert result['broker_socket_access'] is False
    assert result['app_files_visible'] is False and result['credential_names_present'] is False
    assert result['memory_limit']=='1073741824' and result['pids_limit']=='192'
    quota,period=map(int,result['cpu_limit'].split());assert quota/period<=1.5
    assert int(result['capabilities'],16)==0 and result['no_new_privileges']=='1'
    assert (await isolation.provider.run({'operation':'probe'}))['uid']!=result['uid']


@pytest.mark.asyncio
@pytest.mark.sandbox
async def test_real_parser_accepts_text_pdf_and_docx_and_rejects_page_bombs():
    text='Useful business opening hours Monday to Friday.'
    assert await isolation.parse_document(text.encode(),'.txt')==text
    assert text in await isolation.parse_document(docx(text),'.docx')
    assert text in await isolation.parse_document(pdf(content=b'BT /F1 12 Tf 40 700 Td ('+text.encode()+b') Tj ET'),'.pdf')
    with pytest.raises(ValueError,match='200 pages'):await isolation.parse_document(pdf(201),'.pdf')
    with pytest.raises(ValueError,match='200 pages'):
        await isolation.parse_document(docx(extra={'docProps/app.xml':'<Properties><Pages>201</Pages></Properties>'}),'.docx')


@pytest.mark.asyncio
@pytest.mark.parametrize('extra',[
    {'../escape':'evil'},{'/absolute':'evil'},
    {'word/oversized.bin':b'0'*8_000_001},
    {'word/bomb.bin':b'0'*1_000_000},
])
@pytest.mark.sandbox
async def test_docx_paths_expanded_sizes_and_compression_bombs_are_rejected(extra):
    with pytest.raises(ValueError):await isolation.parse_document(docx(extra=extra),'.docx')


@pytest.mark.asyncio
@pytest.mark.sandbox
async def test_docx_entities_and_many_explicit_pages_are_rejected():
    body=io.BytesIO()
    with zipfile.ZipFile(body,'w') as archive:
        archive.writestr('word/document.xml','<!DOCTYPE x [<!ENTITY leak SYSTEM "file:///app/.env">]><x>&leak;</x>')
    with pytest.raises(ValueError,match='DTD'):await isolation.parse_document(body.getvalue(),'.docx')
    with pytest.raises(ValueError,match='200 pages'):
        await isolation.parse_document(docx('Useful business information.'+'<w:br w:type="page"/>'*200),'.docx')


@pytest.mark.asyncio
@pytest.mark.sandbox
async def test_pdf_decompression_is_limited_before_text_extraction():
    body=pdf(content=b' '*5_000_001)
    assert len(body)<20000
    with pytest.raises(ValueError):await isolation.parse_document(body,'.pdf')


@pytest.mark.asyncio
async def test_missing_sandbox_fails_closed_without_in_process_fallback(monkeypatch,tmp_path):
    monkeypatch.setattr(settings,'content_sandbox_socket',str(tmp_path/'missing.sock'))
    with pytest.raises(ValueError,match='isolation service unavailable'):
        await isolation.parse_document(b'Useful business information.','.txt')


@pytest.mark.asyncio
@pytest.mark.sandbox
async def test_real_renderer_cancels_pending_parent_fetch_before_success(monkeypatch):
    entered=asyncio.Event();finished=asyncio.Event();site='https://isolated-render.example'
    async def fetch(url,**kwargs):
        if url==site+'/':return url,b'<main>Useful rendered evidence.</main><script>fetch("/slow")</script>','text/html'
        assert url==site+'/slow';entered.set()
        try:await asyncio.Event().wait()
        finally:finished.set()
    monkeypatch.setattr(knowledge,'safe_fetch',fetch)
    monkeypatch.setattr(website_extraction,'RENDER_SETTLE_MILLISECONDS',300)
    robot=RobotFileParser();robot.parse(['User-agent: *','Allow: /'])
    result=await asyncio.wait_for(website_extraction.rendered_html(site+'/',robot,0),6)
    assert b'Useful rendered evidence.' in result and entered.is_set() and finished.is_set()
    assert (await asyncio.wait_for(isolation.provider.run({'operation':'probe'}),3))['uid']!=0


@pytest.mark.asyncio
@pytest.mark.sandbox
async def test_infinite_browser_script_is_killed_and_next_job_runs(monkeypatch):
    site='https://isolated-render.example'
    entered=asyncio.Event()
    async def fetch(url,**kwargs):
        entered.set();return url,b'<script>while(true){}</script>','text/html'
    monkeypatch.setattr(knowledge,'safe_fetch',fetch)
    monkeypatch.setattr(settings,'content_sandbox_timeout_seconds',10)
    robot=RobotFileParser();robot.parse(['User-agent: *','Allow: /'])
    task=asyncio.create_task(website_extraction.rendered_html(site+'/',robot,0))
    await asyncio.wait_for(entered.wait(),8)
    assert (await asyncio.wait_for(isolation.provider.run({'operation':'health'}),.5))['ready'] is True
    # Start the test's call deadline after Chromium has started, so a cold boot
    # cannot satisfy the assertion without ever executing the malicious page.
    with pytest.raises(TimeoutError):await asyncio.wait_for(task,.5)
    monkeypatch.setattr(settings,'content_sandbox_timeout_seconds',5)
    assert (await asyncio.wait_for(isolation.provider.run({'operation':'probe'}),3))['network_available'] is False


@pytest.mark.asyncio
@pytest.mark.sandbox
async def test_protocol_deadline_closes_a_stalled_job_and_recovers(monkeypatch):
    async def stalled(request):await asyncio.Event().wait()
    monkeypatch.setattr(settings,'content_sandbox_timeout_seconds',.05)
    with pytest.raises(ValueError,match='timed out'):
        await isolation.provider.run({'operation':'render','url':'https://deadline.example',
            'user_agent':'Isolation QA'},stalled)
    monkeypatch.setattr(settings,'content_sandbox_timeout_seconds',5)
    assert (await asyncio.wait_for(isolation.provider.run({'operation':'probe'}),3))['uid']!=0


@pytest.mark.sandbox
def test_readiness_requires_a_reachable_sandbox(client,monkeypatch,tmp_path):
    from studio.readiness import heartbeat
    heartbeat('sandbox-readiness-worker')
    assert client.get('/readyz').status_code==200
    monkeypatch.setattr(settings,'content_sandbox_socket',str(tmp_path/'missing.sock'))
    response=client.get('/readyz')
    assert response.status_code==503 and response.json()['checks']['content_sandbox']=='unavailable'


@pytest.mark.asyncio
@pytest.mark.sandbox
async def test_simultaneous_jobs_never_share_content():
    texts=['Independent document '+str(index)+' private synthetic content.' for index in range(4)]
    assert await asyncio.gather(*(isolation.parse_document(text.encode(),'.txt') for text in texts))==texts


@pytest.mark.sandbox
def test_local_sandbox_start_is_idempotent_and_preserves_a_running_broker(tmp_path):
    import json,os,secrets,subprocess
    from content_sandbox import start,stop
    name='studio-content-restart-'+secrets.token_hex(4)
    try:
        first=start(tmp_path/'broker',name)
        identity=json.loads(subprocess.check_output(['docker','inspect',name]))[0]['Id']
        assert start(tmp_path/'broker',name)==first
        assert json.loads(subprocess.check_output(['docker','inspect',name]))[0]['Id']==identity
    finally:stop(name)
