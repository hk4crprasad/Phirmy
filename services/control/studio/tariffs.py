"""Immutable plan retail terms. Included minutes and synthetic credit are explicit."""
from fastapi import HTTPException
from .config import settings
from .metering import snapshot


def voice_admission(db,call,maximum):
    from .domain import reserve,wallet_state
    mode='production' if call.mode=='live' else 'development'
    tariff=snapshot(db,call.workspace_id,'call:'+call.id,call.id,mode)
    terms=tariff.content
    if terms.get('schema_version',1)<2:
        from sqlalchemy import select
        from .models import Reservation
        previous=db.scalar(select(Reservation).where(Reservation.workspace_id==call.workspace_id,Reservation.call_id==call.id))
        if not previous:reserve(db,call,call.metadata_data.get('budget_minor',0) if call.transport=='pstn' else 0)
        call.metadata_data={**call.metadata_data,'tariff_id':tariff.id,'tariff':'legacy-retained',
                            'billing_basis':'legacy','retail_status':terms.get('status','DRAFT')}
        return maximum
    synthetic=call.mode=='simulation'
    trial=bool(call.metadata_data.get('phone_trial_id'))
    basis='synthetic_credit' if synthetic else 'included' if trial else terms.get('voice_billing','included')
    rate=(terms.get('development_voice_minor_per_minute',600) if call.transport=='pstn' else 0) if synthetic else terms['voice_retail_minor_per_minute']
    amount=call.metadata_data.get('budget_minor',0) if call.transport=='pstn' and not trial else 0
    if basis=='wallet':
        if not settings.paid_activation_enabled or terms['status']!='APPROVED':
            raise HTTPException(409,'Paid voice activation is disabled pending approved prices')
        wallet=wallet_state(db,call.workspace_id)
        if wallet['currency']!=terms['currency']:raise HTTPException(409,'Wallet currency does not match the admitted tariff')
        available=wallet['available_minor']
        budget=min(call.metadata_data.get('budget_minor',(maximum*rate+59)//60),available)
        maximum=min(maximum,budget*60//rate)
        if maximum<1:raise HTTPException(402,'Available wallet balance cannot cover this voice session')
        amount=(maximum*rate+59)//60
    reserve(db,call,amount)
    call.metadata_data={**call.metadata_data,'tariff_id':tariff.id,'tariff':'plan:'+terms['catalog_version']+':'+basis,
        'rate_minor_per_minute':rate,'billing_basis':basis,'retail_status':terms['status'],
        'retail_reservation_minor':amount}
    return maximum


def voice_charge(db,call,connected_ms):
    """Never price a new call from mutable metadata or a later plan edit."""
    from .models import TariffSnapshot
    tariff_id=call.metadata_data.get('tariff_id')
    tariff=db.get(TariffSnapshot,tariff_id) if tariff_id else None
    if tariff_id and (not tariff or tariff.workspace_id!=call.workspace_id or tariff.call_id!=call.id):
        raise HTTPException(409,'Call tariff is unavailable for settlement')
    if not tariff or tariff.content.get('schema_version',1)<2:
        # Historical calls retain their originally admitted legacy terms.
        rate=int(call.metadata_data.get('rate_minor_per_minute',0))
        return (connected_ms*rate+59999)//60000
    terms=tariff.content
    if terms['mode']=='development':
        rate=terms['development_voice_minor_per_minute'] if terms.get('call_transport')=='pstn' else 0
    elif terms.get('voice_billing','included')=='included' or terms.get('phone_trial'):
        return 0 # Measured minutes consume the included plan allowance, not wallet money.
    else:rate=terms['voice_retail_minor_per_minute']
    return (connected_ms*rate+59999)//60000
