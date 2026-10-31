"""Immutable invoice snapshots, bounded isolated PDFs and email-outbox delivery."""
import asyncio
from datetime import datetime
import html
import hashlib
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .db import now,session_scope
from .models import Invoice,InvoiceDelivery,InvoiceSequence,Workspace
from .gst import financial_year
from .domain import enqueue,owned


def issue(db,workspace_id,operation_key,quote,source_id,*,kind='invoice',original_number=None):
    db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
    previous=db.scalar(select(Invoice).where(Invoice.workspace_id==workspace_id,Invoice.operation_key==operation_key))
    if previous:
        if (previous.kind,previous.snapshot['source_id'],previous.snapshot.get('original_invoice_number'))!=(kind,source_id,original_number) or any(previous.snapshot.get(key)!=value for key,value in quote.items()):
            from fastapi import HTTPException
            raise HTTPException(409,'Invoice operation conflicts with its original snapshot')
        return previous
    seller=quote['seller'];stamp=now();year=financial_year(stamp)
    status='FINAL' if quote.get('authorized_paid') and quote.get('price_status')=='APPROVED' and seller['status']=='APPROVED' and quote.get('payment_mode')=='live' else 'DRAFT'
    series=seller['entity_id'] if status=='FINAL' else 'draft-'+hashlib.sha256(seller['entity_id'].encode()).hexdigest()[:32]
    prefix=seller['invoice_prefix'] if status=='FINAL' else 'DRF'
    sequence=db.scalar(select(InvoiceSequence).where(InvoiceSequence.entity_id==series,InvoiceSequence.financial_year==year).with_for_update())
    if not sequence:
        try:
            with db.begin_nested():
                sequence=InvoiceSequence(entity_id=series,financial_year=year,last_number=0);db.add(sequence);db.flush()
        except IntegrityError:
            sequence=db.scalar(select(InvoiceSequence).where(InvoiceSequence.entity_id==series,InvoiceSequence.financial_year==year).with_for_update())
    sequence.last_number+=1
    if sequence.last_number>999999:raise ValueError('Invoice numbering range requires a reviewed new prefix')
    number=f'{prefix}/{year}/{sequence.last_number:06d}'
    if len(number)>16:raise ValueError('Invoice identifier exceeds legal format budget')
    snapshot={**quote,'issued_at':stamp.isoformat(),'number':number,'source_id':source_id,'kind':kind,
              'original_invoice_number':original_number,'document_status':status}
    row=Invoice(workspace_id=workspace_id,operation_key=operation_key,kind=kind,status=status,
        entity_id=seller['entity_id'],number=number,snapshot=snapshot)
    db.add(row);db.flush()
    db.add(InvoiceDelivery(workspace_id=workspace_id,invoice_id=row.id))
    enqueue(db,workspace_id,'invoice_pdf',{'invoice_id':row.id})
    return row


def money(amount):return f'INR {amount//100:,}.{amount%100:02d}'


def document(snapshot):
    seller=snapshot['seller'];buyer=snapshot['buyer'];tax=snapshot['tax']
    def escape(value):return html.escape(str(value),quote=True)
    kind='Credit note' if snapshot['kind']=='credit_note' else 'Tax invoice'
    draft=snapshot['document_status']!='FINAL'
    issued=datetime.fromisoformat(snapshot['issued_at']).astimezone(ZoneInfo('Asia/Kolkata')).date().isoformat()
    rows=[('Taxable value',tax['net_minor']),('CGST',tax['cgst_minor']),('SGST',tax['sgst_minor']),('IGST',tax['igst_minor']),('Total',tax['gross_minor'])]
    lines=''.join('<tr><td>'+escape(label)+'</td><td class="amount">'+escape(money(amount))+'</td></tr>' for label,amount in rows)
    original=('<p>Original invoice: '+escape(snapshot['original_invoice_number'])+'</p>') if snapshot.get('original_invoice_number') else ''
    return '<!doctype html><html><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'; font-src \'none\'"><style>'+'''
body{font-family:"Noto Sans","Noto Sans Devanagari",sans-serif;font-size:11pt;color:#18212b;line-height:1.5}
h1{font-size:24pt}h2{font-size:15pt}.draft{border:2px solid #b36b00;padding:12px;color:#874d00}
.columns{display:flex;gap:30px}.columns>section{flex:1;overflow-wrap:anywhere}table{width:100%;border-collapse:collapse;margin:24px 0}
td,th{border-bottom:1px solid #ccd4dd;padding:8px;text-align:left}.amount{text-align:right}.address{white-space:pre-wrap}
.reference{font-family:monospace;font-variant-ligatures:none}footer{margin-top:25px;font-size:9pt;color:#52616d}tr{break-inside:avoid}
'''+'</style></head><body>'+('<p class="draft">DRAFT — Not a tax invoice. Business details and tax treatment require review.</p>' if draft else '')+f'''
<h1>{escape(kind)}</h1><p><strong>{escape(snapshot['number'])}</strong> · {escape(issued)}</p>
<div class="columns"><section><h2>{escape(seller['legal_name'])}</h2><p class="address">{escape(seller['address'])}</p><p>GSTIN: {escape(seller['gstin'] or 'DRAFT: required')}<br>State: {escape(seller['state_code'])}</p></section>
<section><h2>Bill to</h2><p>{escape(buyer['legal_name'])}</p><p class="address">{escape(buyer['address'])}</p><p>GSTIN: {escape(buyer.get('gstin') or 'Not supplied')}<br>Place of supply: {escape(tax['place_of_supply'])}</p></section></div>
<p>{escape(snapshot.get('description','Phirmy services'))} · SAC {escape(tax['sac'])} · GST {tax['gst_rate_basis_points']/100:g}%</p>
{original}<table><thead><tr><th>Description</th><th class="amount">Amount</th></tr></thead><tbody>{lines}</tbody></table>
<p>Payment reference: <span class="reference">{escape(snapshot['source_id'])}</span></p><footer>{escape(seller['payment_terms'])}<br>{escape(seller['support_email'])}</footer></body></html>'''


async def invoice_job(job_id):
    from .job_control import get_job
    from .isolation import invoice_pdf
    from .storage import get_store
    from .mail_outbox import enqueue_email
    def load():
        with session_scope(write=True) as db:
            job=get_job(db,job_id);row=owned(db,Invoice,job.workspace_id,job.payload['invoice_id'])
            delivery=db.scalar(select(InvoiceDelivery).where(InvoiceDelivery.workspace_id==job.workspace_id,InvoiceDelivery.invoice_id==row.id))
            job.phase='rendering_invoice'
            return job.workspace_id,row.id,row.snapshot,delivery.object_key
    workspace_id,identity,snapshot,key=await asyncio.to_thread(load)
    if not key:
        body=await invoice_pdf(document(snapshot))
        key=await asyncio.to_thread(get_store().put,workspace_id,'invoices',body,'application/pdf')
    def save():
        with session_scope(write=True) as db:
            get_job(db,job_id)
            row=owned(db,Invoice,workspace_id,identity)
            delivery=db.scalar(select(InvoiceDelivery).where(InvoiceDelivery.workspace_id==workspace_id,InvoiceDelivery.invoice_id==identity).with_for_update())
            delivery.object_key=key;delivery.state='ready'
            recipient=snapshot['buyer'].get('email')
            if recipient:
                enqueue_email(db,recipient,('DRAFT ' if row.status=='DRAFT' else '')+'Phirmy '+row.kind.replace('_',' ')+' '+row.number,
                    'Your billing document is attached. '+('This is a DRAFT and is not a tax invoice.' if row.status=='DRAFT' else 'Keep this document for your records.'),
                    operation_key='invoice:'+row.id,
                    attachments=[{'workspace_id':workspace_id,'object_key':key,'filename':row.number.replace('/','-')+'.pdf'}],invoice_id=row.id)
    await asyncio.to_thread(save)
