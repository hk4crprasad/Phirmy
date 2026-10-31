import json
from datetime import datetime,timezone
import pytest
from studio import gst
from studio.config import settings


def test_checked_in_business_is_draft_and_tax_split_is_configurable():
    business=gst.business();assert business['status']=='DRAFT' and business['gstin']==''
    intra=gst.tax_lines(10000,business['state_code'])
    inter=gst.tax_lines(10000,'07')
    assert (intra['net_minor'],intra['gross_minor'],intra['cgst_minor'],intra['sgst_minor'],intra['igst_minor'])==(10000,11800,900,900,0)
    assert (inter['cgst_minor'],inter['sgst_minor'],inter['igst_minor'])==(0,0,1800)
    included=gst.tax_lines(10000,'07',{**business,'prices_include_gst':True})
    assert included['net_minor']==8475 and included['tax_minor']==1525 and included['gross_minor']==10000


def test_inclusive_and_exclusive_rounding_always_balances_minor_units():
    for included in [False,True]:
        business={**gst.business(),'prices_include_gst':included}
        for amount in [1,2,3,5,99,100,101,999,10001,1_000_000]:
            value=gst.tax_lines(amount,'29',business)
            assert value['net_minor']+value['tax_minor']==value['gross_minor']
            assert value['cgst_minor']+value['sgst_minor']+value['igst_minor']==value['tax_minor']
            if included:assert value['gross_minor']==amount


def test_gstin_local_checksum_and_state_validation_do_not_claim_registry_verification():
    assert gst.valid_gstin('27AAPFU0939F1ZV')
    prefix='29ABCDE1234F1Z';gstin=prefix+gst.gstin_check_character(prefix)
    assert gst.valid_gstin(gstin) and not gst.valid_gstin(gstin[:-1]+('A' if gstin[-1]!='A' else 'B'))
    profile=gst.BillingProfile(legal_name='Synthetic customer',address='Synthetic billing address',state_code='29',gstin=' '+gstin.lower()+' ',email='billing@example.test')
    assert profile.gstin==gstin
    with pytest.raises(ValueError):gst.BillingProfile(**{**profile.model_dump(),'state_code':'07'})
    with pytest.raises(ValueError):gst.BillingProfile(**{**profile.model_dump(),'email':'billing@example.test\nBcc:other@example.test'})


def test_approved_business_cannot_contain_placeholder_or_missing_registration(monkeypatch,tmp_path):
    body=gst.business();body.pop('content_hash',None);body['status']='APPROVED'
    path=tmp_path/'business.json';path.write_text(json.dumps(body));monkeypatch.setattr(settings,'billing_business_config_path',str(path))
    with pytest.raises(ValueError,match='configuration'):gst.business()
    prefix='29ABCDE1234F1Z'
    body.update(legal_name='Synthetic invoice business',address='Synthetic registered address',gstin=prefix+gst.gstin_check_character(prefix),support_email='support@example.test',payment_terms='Due on receipt')
    path.write_text(json.dumps(body));assert gst.business()['status']=='APPROVED'


def test_financial_year_uses_indian_midnight_at_april_boundary():
    assert gst.financial_year(datetime(2026,3,31,18,29,tzinfo=timezone.utc))=='2526'
    assert gst.financial_year(datetime(2026,3,31,18,30,tzinfo=timezone.utc))=='2627'


def quote():
    return {'seller':gst.business(),'buyer':{'legal_name':'ग्राहक <script>alert(1)</script>',
        'address':'Synthetic billing address','state_code':'07','gstin':'','email':'billing@example.test'},
        'tax':gst.tax_lines(10000,'07'),'price_status':'DRAFT','authorized_paid':False,'payment_mode':'test',
        'description':'Synthetic invoice service'}


@pytest.mark.asyncio
@pytest.mark.sandbox
async def test_actual_isolated_invoice_pdf_and_outbox_attachment_are_replay_safe(account):
    import io
    from pathlib import Path
    from email import policy
    from email.parser import BytesParser
    from pypdf import PdfReader
    from sqlalchemy import select,func
    from studio import invoices
    from studio.db import session_scope
    from studio.models import Invoice,InvoiceDelivery,Job,EmailOutbox
    from studio.workers import execute_job
    from studio.mail_outbox import process_outbox
    _,ws,_=account
    with session_scope(write=True) as db:
        first=invoices.issue(db,ws,'capture:invoice-fixture',quote(),'payment_fixture')
        identity=first.id
        assert invoices.issue(db,ws,'capture:invoice-fixture',quote(),'payment_fixture').id==identity
        assert first.status=='DRAFT' and len(first.number)<=16
        rendered=invoices.document(first.snapshot)
        assert '<script>alert' not in rendered and '&lt;script&gt;' in rendered
        job_id=db.scalar(select(Job.id).where(Job.kind=='invoice_pdf'))
    await execute_job(job_id)
    await execute_job(job_id)
    with session_scope() as db:
        delivery=db.scalar(select(InvoiceDelivery).where(InvoiceDelivery.invoice_id==identity))
        assert delivery.state=='ready'
        outbox=db.scalar(select(EmailOutbox).where(EmailOutbox.operation_key=='invoice:'+identity));mail_id=outbox.id
        assert db.scalar(select(func.count()).select_from(Invoice))==1
        assert db.get(Job,job_id).state=='completed'
    process_outbox()
    message=BytesParser(policy=policy.default).parsebytes((Path(settings.data_dir)/'mail-outbox'/f'{mail_id}.eml').read_bytes())
    attached=list(message.iter_attachments())
    assert len(attached)==1 and attached[0].get_content_type()=='application/pdf'
    pdf=attached[0].get_payload(decode=True);assert pdf.startswith(b'%PDF')
    text='\n'.join(page.extract_text() for page in PdfReader(io.BytesIO(pdf)).pages)
    import unicodedata
    text=unicodedata.normalize('NFKC',text)
    assert 'DRAFT' in text and 'payment_fixture' in text
    assert 'INR 118.00' in text and 'INR 18.00' in text
    # Poppler reads Chromium's complex-script ActualText; pypdf does not
    # reconstruct every Devanagari conjunct from shaped glyph mappings.
    import subprocess
    accessible=subprocess.check_output(['pdftotext','-','-'],input=pdf,timeout=10).decode()
    assert 'ग्राहक' in accessible
    with session_scope() as db:assert db.scalar(select(InvoiceDelivery)).emailed_at is not None


def test_invoice_financial_snapshot_is_immutable_and_conflicting_replay_is_rejected(account):
    from fastapi import HTTPException
    from sqlalchemy import update,delete
    from sqlalchemy.exc import DBAPIError
    from studio import invoices
    from studio.db import session_scope,engine
    from studio.models import Invoice
    _,ws,_=account
    with session_scope(write=True) as db:
        row=invoices.issue(db,ws,'capture:immutable-invoice',quote(),'payment_fixture');identity=row.id
    with pytest.raises(HTTPException,match='original snapshot'):
        with session_scope(write=True) as db:invoices.issue(db,ws,'capture:immutable-invoice',{**quote(),'description':'changed'},'payment_fixture')
    for statement in [update(Invoice).where(Invoice.id==identity).values(snapshot={}),delete(Invoice).where(Invoice.id==identity)]:
        with pytest.raises(DBAPIError):
            with engine.begin() as db:db.execute(statement)


def test_draft_invoice_numbers_cannot_consume_approved_live_series(account,monkeypatch,tmp_path):
    from billing_fakes import enable_checkout
    from studio import invoices
    from studio.db import session_scope
    _,ws,_=account
    enable_checkout(monkeypatch,tmp_path)
    preview={**quote(),'seller':gst.business(),'price_status':'APPROVED','authorized_paid':True}
    with session_scope(write=True) as db:
        draft=invoices.issue(db,ws,'draft-series',preview,'draft_payment')
        final=invoices.issue(db,ws,'final-series',{**preview,'payment_mode':'live'},'live_payment')
        assert draft.status=='DRAFT' and draft.number.startswith('DRF/')
        assert final.status=='FINAL' and final.number.startswith('VS/')
        assert draft.number.endswith('/000001') and final.number.endswith('/000001')
