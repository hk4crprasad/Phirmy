"""Configurable GST arithmetic and local GSTIN checks; defaults require legal review.

A syntactically valid GSTIN is not government verification. DRAFT documents are
not tax invoices. Business registration, SAC and tax treatment need approval.
"""
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Literal

from pydantic import BaseModel,ConfigDict,Field,StrictInt,model_validator,field_validator
from .config import settings

ALPHABET='0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ'


def gstin_check_character(prefix):
    if len(prefix)!=14 or any(value not in ALPHABET for value in prefix):raise ValueError('Invalid GSTIN prefix')
    total=0;factor=2
    for value in reversed(prefix):
        product=ALPHABET.index(value)*factor;total+=product//36+product%36;factor=3-factor
    return ALPHABET[(36-total%36)%36]


def valid_state(value):return isinstance(value,str) and bool(re.fullmatch('[0-9]{2}',value)) and 1<=int(value)<=38


def valid_gstin(value):
    return bool(re.fullmatch(r'[0-9]{2}[A-Z]{5}[0-9]{4}[A-Z][1-9A-Z]Z[0-9A-Z]',value)
        and valid_state(value[:2]) and gstin_check_character(value[:14])==value[-1])


class Business(BaseModel):
    model_config=ConfigDict(extra='forbid')
    version:str=Field(min_length=1,max_length=80)
    status:Literal['DRAFT','APPROVED']
    entity_id:str=Field(pattern=r'^[a-zA-Z0-9_-]{1,40}$')
    legal_name:str=Field(min_length=1,max_length=160)
    address:str=Field(min_length=1,max_length=1000)
    state_code:str
    gstin:str=Field(max_length=15)
    sac:str=Field(pattern=r'^[0-9]{6}$')
    gst_rate_basis_points:StrictInt=Field(ge=0,le=10000)
    prices_include_gst:bool=False
    invoice_prefix:str=Field(pattern=r'^[A-Z0-9]{1,4}$')
    support_email:str=Field(default='',max_length=254)
    payment_terms:str=Field(max_length=1000)
    dunning_grace_days:StrictInt=Field(ge=0,le=30)
    subscription_authorization_max_minor:StrictInt=Field(ge=0,le=100000,default=1000)
    refund_policy:Literal['unspent_wallet_only']='unspent_wallet_only'
    downgrade_plan:str=Field(default='free',max_length=40)

    @model_validator(mode='after')
    def complete_approved_business(self):
        if not valid_state(self.state_code):raise ValueError('Invalid seller state')
        if self.gstin and (not valid_gstin(self.gstin) or self.gstin[:2]!=self.state_code):raise ValueError('Invalid seller GSTIN or state')
        if self.status=='APPROVED':
            if self.invoice_prefix=='DRF':raise ValueError('DRF is reserved for draft documents')
            if not self.gstin or any(value.strip().upper().startswith('DRAFT:') for value in [self.legal_name,self.address,self.payment_terms]):
                raise ValueError('Approved invoice business details must be complete')
            if not self.support_email or '\n' in self.support_email or '@' not in self.support_email:raise ValueError('Supply a business contact email')
        return self


class BillingProfile(BaseModel):
    model_config=ConfigDict(extra='forbid')
    legal_name:str=Field(min_length=1,max_length=160)
    address:str=Field(min_length=1,max_length=1000)
    state_code:str
    gstin:str=Field(default='',max_length=15)
    email:str=Field(min_length=3,max_length=254)

    @field_validator('gstin',mode='before')
    @classmethod
    def normalize_gstin(cls,value):return value.strip().upper() if isinstance(value,str) else value

    @model_validator(mode='after')
    def consistent_tax_identity(self):
        if not valid_state(self.state_code):raise ValueError('Choose a valid billing state')
        if self.gstin and (not valid_gstin(self.gstin) or self.gstin[:2]!=self.state_code):raise ValueError('GSTIN checksum or billing state is invalid')
        if any(value in self.email for value in ['\r','\n']) or '@' not in self.email:raise ValueError('Use a billing email address')
        return self


_cache={};_lock=threading.RLock()


def business():
    path=Path(settings.billing_business_config_path)
    try:
        stat=path.stat();identity=(str(path),stat.st_mtime_ns,stat.st_size)
        with _lock:
            if identity not in _cache:
                parsed=Business.model_validate_json(path.read_text());_cache.clear();_cache[identity]=parsed.model_dump_json()
            body=json.loads(_cache[identity])
    except (OSError,ValueError):raise ValueError('Invoice business configuration is unavailable or invalid') from None
    canonical=json.dumps(body,sort_keys=True,separators=(',',':'))
    return {**body,'content_hash':hashlib.sha256(canonical.encode()).hexdigest()}


def round_ratio(numerator,denominator):
    if type(numerator) is not int or numerator<0 or type(denominator) is not int or denominator<=0:raise ValueError('Invalid monetary ratio')
    return (numerator*2+denominator)//(denominator*2)


def tax_lines(amount_minor,state_code,details=None):
    details=details or business()
    if type(amount_minor) is not int or not 0<=amount_minor<=1_000_000_000:raise ValueError('Invalid taxable amount')
    if not valid_state(state_code):raise ValueError('Invalid place of supply')
    rate=details['gst_rate_basis_points']
    if details['prices_include_gst']:
        gross=amount_minor;net=round_ratio(gross*10000,10000+rate);tax=gross-net
    else:
        net=amount_minor;tax=round_ratio(net*rate,10000);gross=net+tax
    intra=state_code==details['state_code']
    return {'net_minor':net,'tax_minor':tax,'gross_minor':gross,'gst_rate_basis_points':rate,
            'cgst_minor':tax//2 if intra else 0,'sgst_minor':tax-tax//2 if intra else 0,
            'igst_minor':0 if intra else tax,'place_of_supply':state_code,'sac':details['sac'],
            'prices_include_gst':details['prices_include_gst']}


def financial_year(stamp):
    from zoneinfo import ZoneInfo
    local=stamp.astimezone(ZoneInfo('Asia/Kolkata'));start=local.year if local.month>=4 else local.year-1
    return f'{start%100:02d}{(start+1)%100:02d}'
