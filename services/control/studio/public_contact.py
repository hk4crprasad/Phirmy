"""Public Phirmy enquiries, queued transactionally to a fixed support inbox."""
from html import escape
import json
from typing import Literal
from uuid import UUID

from fastapi import APIRouter, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from .config import settings
from .db import session_scope
from .mail_outbox import enqueue_email
from .models import EmailOutbox
from .rate_limits import limiter
from .secrets import decrypt

router = APIRouter(prefix='/v1/public', tags=['Public enquiries'])
RECIPIENT = 'support@phirmy.com'
INTERESTS = {
    'voice': 'AI voice agents',
    'chat': 'Website chat agents',
    'both': 'Voice and chat',
    'exploring': 'Exploring the possibilities',
}


class Enquiry(BaseModel):
    model_config = ConfigDict(extra='forbid', str_strip_whitespace=True)
    name: str = Field(min_length=2, max_length=100)
    email: EmailStr = Field(max_length=254)
    company: str = Field(default='', max_length=150)
    interest: Literal['voice', 'chat', 'both', 'exploring']
    message: str = Field(min_length=20, max_length=4000)
    contact_permission: Literal[True]
    # An invisible, non-focusable field. Real visitors leave it empty.
    fax_number: str = Field(default='', max_length=200)

    @field_validator('name', 'company')
    @classmethod
    def single_line(cls, value):
        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError('Use a single line of text')
        return value


def check_contact_origin(request):
    allowed = {settings.contact_site_origin.rstrip('/'), 'https://phirmy.com', 'https://www.phirmy.com'}
    if settings.app_env != 'production':
        allowed.update({'http://localhost:3200', 'http://127.0.0.1:3200',
                        'http://localhost:3202', 'http://127.0.0.1:3202'})
    if request.headers.get('origin') not in allowed:
        raise HTTPException(403, 'Please send your enquiry through the Phirmy contact page.')


def content(body, reference):
    topic = INTERESTS[body.interest]
    fields = [('Name', body.name), ('Email', str(body.email)),
              ('Company', body.company or 'Not provided'), ('Interested in', topic)]
    text = 'New Phirmy website enquiry\n\n' + '\n'.join(f'{label}: {value}' for label, value in fields)
    text += f'\n\nMessage:\n{body.message}\n\nPermission: May contact me about this enquiry.\nReference: {reference}\nSource: https://phirmy.com/contact\n'
    rows = ''.join(f'<tr><td style="padding:8px 0;color:#6b6b65;width:120px">{label}</td>'
                   f'<td style="padding:8px 0;color:#252521">{escape(value)}</td></tr>' for label, value in fields)
    html = f'''<!doctype html><html lang="en"><body style="margin:0;background:#f5f5f1;padding:32px 16px;font-family:Arial,sans-serif">
      <div style="max-width:580px;margin:auto;background:#fff;border:1px solid #e4e4de;border-radius:14px;overflow:hidden">
      <div style="background:#20211e;padding:28px 32px;color:#fff"><strong style="font-size:22px;letter-spacing:4px">PHIRMY</strong>
      <p style="font-size:10px;letter-spacing:2px;color:#ccc">BUILD. SCALE. TOGETHER.</p></div>
      <div style="padding:32px"><p style="font-size:11px;letter-spacing:1px;color:#73736b">A NEW CONVERSATION STARTS HERE</p>
      <h1 style="font-size:26px;font-weight:normal;color:#242420">Someone has something in mind.</h1>
      <table style="width:100%;font-size:14px;border-collapse:collapse">{rows}</table>
      <div style="padding:20px;background:#f5f5f0;border:1px solid #e8e8e1;border-radius:8px;margin:24px 0;color:#43433d;font-size:14px;line-height:1.8;white-space:pre-wrap">{escape(body.message)}</div>
      <p style="font-size:12px;color:#696961">The sender agreed to be contacted about this enquiry. Reply to this email to get in touch.</p>
      <p style="font-size:11px;color:#73736b">Reference: {escape(reference)}<br>Sent from phirmy.com/contact</p></div></div></body></html>'''
    return text, html


def existing_enquiry(key, text):
    with session_scope() as db:
        row = db.scalar(select(EmailOutbox).where(EmailOutbox.operation_key == key))
        if row is None:
            return False
        if json.loads(decrypt(row.encrypted_payload))['body'] != text:
            raise HTTPException(409, 'This submission reference has already been used. Please start a new enquiry.')
        return True


@router.post('/contact', status_code=202, openapi_extra={
    'parameters': [
        {'name': 'Idempotency-Key', 'in': 'header', 'required': True,
         'schema': {'type': 'string', 'format': 'uuid'}, 'description': 'A fresh UUID v4, reused for retries of the same enquiry.'},
        {'name': 'Origin', 'in': 'header', 'required': True, 'schema': {'type': 'string'},
         'description': 'The configured Phirmy contact-site origin.'},
    ]
}, responses={202: {'description': 'Enquiry received by the durable outbox; not a confirmation of SMTP delivery.'},
              403: {'description': 'Origin not permitted'}, 409: {'description': 'Reference reused with different content'},
              429: {'description': 'Enquiry rate limit exceeded'}, 503: {'description': 'SMTP not configured'}})
def contact(body: Enquiry, request: Request, response: Response):
    check_contact_origin(request)
    response.headers['Cache-Control'] = 'no-store'
    raw_key = request.headers.get('idempotency-key', '')
    try:
        reference = UUID(raw_key)
        if reference.version != 4 or str(reference) != raw_key.lower():
            raise ValueError()
    except ValueError:
        raise HTTPException(422, 'A valid enquiry reference is required.') from None
    reference = str(reference)
    answer = {'status': 'received', 'reference': reference}
    ip = request.client.host if request.client else 'unknown'
    limiter.check('public-contact-attempt:' + ip, 20, 3600)
    if body.fax_number:
        # Avoid confirming the honeypot to automated senders; never enqueue it.
        return answer
    text, html = content(body, reference)
    key = 'public-contact:' + reference
    if existing_enquiry(key, text):
        return answer
    if not settings.smtp_host and settings.app_env != 'test':
        raise HTTPException(503, 'We cannot receive messages right now. Please email support@phirmy.com.')
    limiter.check('public-contact-ip:' + ip, 5, 3600)
    limiter.check('public-contact-email:' + str(body.email).casefold(), 3, 86400)
    limiter.check('public-contact-global', 100, 3600)
    try:
        with session_scope(write=True) as db:
            identity = enqueue_email(db, RECIPIENT, 'Phirmy enquiry — ' + INTERESTS[body.interest], text,
                          operation_key=key, reply_to=str(body.email), html_body=html)
            stored = db.get(EmailOutbox, identity)
            if json.loads(decrypt(stored.encrypted_payload))['body'] != text:
                raise HTTPException(409, 'This reference belongs to a different enquiry.')
    except IntegrityError:
        # A simultaneous retry can win the unique operation-key race.
        if not existing_enquiry(key, text):
            raise
    return answer
