from fastapi import APIRouter,Depends,Query
from fastapi import HTTPException,Response
import asyncio
from sqlalchemy import select

from .security import principal,db_dependency
from .models import CallCostRecord,TariffSnapshot,WorkspaceSubscription,PlanCatalogSnapshot,Invoice,InvoiceDelivery
from .db import as_dict
from .plans import public_plans
from .metering import usage_summary

router=APIRouter()


@router.get('/v1/workspaces/{workspace_id}/billing/profile')
def billing_profile(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:read')
    from .billing_quote import profile
    return profile(db,workspace_id)


from .gst import BillingProfile


@router.put('/v1/workspaces/{workspace_id}/billing/profile')
def save_profile(workspace_id:str,body:BillingProfile,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:write')
    from .plans import subscription
    from .security import audit
    row=subscription(db,workspace_id);row.billing_profile=body.model_dump()
    audit(db,actor,'billing.profile_updated',workspace_id,{'fields':list(body.model_dump())})
    return row.billing_profile


@router.get('/v1/workspaces/{workspace_id}/billing/quote')
def quote(workspace_id:str,amount_minor:int=Query(default=10000,ge=10000,le=10000000),
          purpose:str=Query(default='wallet',pattern='^(wallet|subscription)$'),plan_slug:str|None=Query(default=None,max_length=40),
          actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:read')
    from .billing_quote import preview
    return preview(db,workspace_id,amount_minor,purpose=purpose,plan_slug=plan_slug)


@router.get('/v1/workspaces/{workspace_id}/billing/invoices')
def invoices(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:read')
    rows=db.execute(select(Invoice,InvoiceDelivery).outerjoin(InvoiceDelivery,
        (InvoiceDelivery.workspace_id==Invoice.workspace_id)&(InvoiceDelivery.invoice_id==Invoice.id)).where(
        Invoice.workspace_id==workspace_id).order_by(Invoice.created_at.desc(),Invoice.id.desc()).limit(100))
    return {'items':[{'id':row.id,'number':row.number,'kind':row.kind,'status':row.status,'created_at':row.created_at.isoformat(),
        'tax':row.snapshot['tax'],'download_ready':bool(delivery and delivery.state=='ready'),
        'emailed_at':delivery.emailed_at.isoformat() if delivery and delivery.emailed_at else None} for row,delivery in rows]}


@router.get('/v1/workspaces/{workspace_id}/billing/invoices/{invoice_id}/pdf')
async def invoice_pdf(workspace_id:str,invoice_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:read')
    from .domain import owned
    row=owned(db,Invoice,workspace_id,invoice_id)
    delivery=db.scalar(select(InvoiceDelivery).where(InvoiceDelivery.workspace_id==workspace_id,InvoiceDelivery.invoice_id==invoice_id))
    if not delivery or delivery.state!='ready' or not delivery.object_key:raise HTTPException(409,'Invoice PDF is still being prepared')
    from .storage import get_store
    try:body=await asyncio.to_thread(get_store().get,workspace_id,delivery.object_key)
    except Exception:raise HTTPException(503,'Invoice document is temporarily unavailable') from None
    if len(body)>5_000_000 or not body.startswith(b'%PDF'):raise HTTPException(503,'Invoice document requires regeneration')
    return Response(body,media_type='application/pdf',headers={'Content-Disposition':'attachment; filename="'+row.number.replace('/','-')+'.pdf"'})


@router.get('/v1/workspaces/{workspace_id}/billing/tariff')
def tariff(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:read')
    from .plans import catalog
    from .config import settings
    current=db.scalar(select(WorkspaceSubscription).where(WorkspaceSubscription.workspace_id==workspace_id))
    body=db.get(PlanCatalogSnapshot,current.catalog_id).content if current else catalog()
    slug=current.plan_slug if current else 'free';plan=body['plans'][slug]
    return {'version':body['version'],'status':body['status'],'currency':body['currency'],'plan':slug,
            'voice_billing':plan.get('voice_billing','included'),'voice_retail_minor_per_minute':plan['voice_retail_minor_per_minute'],
            'chat_turn_retail_minor':plan['chat_turn_retail_minor'],
            'paid_activation_enabled':settings.paid_activation_enabled and body['status']=='APPROVED'}


@router.get('/v1/public/plans')
def plans():return public_plans()


@router.get('/v1/workspaces/{workspace_id}/billing/usage')
def usage(workspace_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:read')
    return usage_summary(db,workspace_id,shared_user_id=actor.user_id if actor.key_scopes is None else None)


@router.get('/v1/workspaces/{workspace_id}/calls/{call_id}/costs')
def costs(workspace_id:str,call_id:str,actor=Depends(principal),db=Depends(db_dependency,scope='function')):
    actor.require('billing:read')
    from .domain import owned
    from .models import Call
    owned(db,Call,workspace_id,call_id)
    rows=list(db.scalars(select(CallCostRecord).where(CallCostRecord.workspace_id==workspace_id,CallCostRecord.call_id==call_id)))
    tariff=db.scalar(select(TariffSnapshot).where(TariffSnapshot.workspace_id==workspace_id,TariffSnapshot.call_id==call_id))
    return {'currency':'INR','status':tariff.content['status'] if tariff else 'DRAFT','cost_micro_minor':sum(row.cost_micro_minor for row in rows),
            'retail_terms':{key:tariff.content.get(key) for key in ['catalog_version','plan','mode','voice_billing','voice_retail_minor_per_minute']} if tariff else None,
            'items':[as_dict(row) for row in rows]}
