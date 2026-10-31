"""Transactional email, leased worker delivery, bounded retry and private dev spool."""
from datetime import timedelta
from email.message import EmailMessage
import json
import os
from pathlib import Path
import smtplib
import ssl

from sqlalchemy import or_, select, update

from .config import settings
from .db import now, session_scope, uid
from .models import EmailOutbox
from .secrets import decrypt, encrypt


def enqueue_email(db, recipient, subject, body, *, operation_key=None, noop=False,attachments=None,invoice_id=None,reply_to=None,html_body=None):
    if any('\n' in value or '\r' in value for value in [recipient, subject]):
        raise ValueError('Invalid email headers')
    if len(recipient) > 254 or len(subject) > 200:
        raise ValueError('Email header too long')
    if reply_to is not None:
        from pydantic import TypeAdapter, EmailStr
        reply_to = str(TypeAdapter(EmailStr).validate_python(reply_to))
        if any(char in reply_to for char in ('\r', '\n')):
            raise ValueError('Invalid reply address')
    attachments=attachments or []
    if len(attachments)>3:raise ValueError('Too many email attachments')
    import re
    for item in attachments:
        if set(item)!={'workspace_id','object_key','filename'} or not item['object_key'].startswith(item['workspace_id']+'/invoices/'):
            raise ValueError('Only scoped invoice attachments are supported')
        if not re.fullmatch(r'[A-Za-z0-9._-]{1,160}\.pdf',item['filename']):raise ValueError('Invalid invoice filename')
    operation_key = operation_key or 'email:' + uid()
    existing = db.scalar(select(EmailOutbox).where(EmailOutbox.operation_key == operation_key))
    if existing:
        return existing.id
    row = EmailOutbox(operation_key=operation_key, recipient=recipient, subject=subject,
                      encrypted_payload=encrypt(json.dumps({'body':body,'noop':noop,'attachments':attachments,'invoice_id':invoice_id,'reply_to':reply_to,'html_body':html_body})))
    db.add(row)
    db.flush()
    return row.id


def deliver_message(recipient, subject, payload, message_id):
    if payload.get('noop'):
        return
    message = EmailMessage()
    message['From'], message['To'], message['Subject'] = settings.smtp_from, recipient, subject
    message['Message-ID'] = '<' + message_id + '@voice-studio-outbox>'
    if payload.get('reply_to'):
        message['Reply-To'] = payload['reply_to']
    message.set_content(payload['body'])
    if payload.get('html_body'):
        message.add_alternative(payload['html_body'], subtype='html')
    total=0
    for item in payload.get('attachments',[]):
        from .storage import get_store
        if not item['object_key'].startswith(item['workspace_id']+'/invoices/'):raise ValueError('Invalid invoice attachment scope')
        body=get_store().get(item['workspace_id'],item['object_key']);total+=len(body)
        if not body.startswith(b'%PDF') or len(body)>5_000_000 or total>10_000_000:raise ValueError('Invalid invoice PDF attachment')
        message.add_attachment(body,maintype='application',subtype='pdf',filename=item['filename'])
    if settings.smtp_host:
        smtp_class = smtplib.SMTP_SSL if settings.smtp_security == 'ssl' else smtplib.SMTP
        options = {'timeout': 15}
        if settings.smtp_security == 'ssl':
            options['context'] = ssl.create_default_context()
        with smtp_class(settings.smtp_host, settings.smtp_port, **options) as smtp:
            if settings.smtp_security == 'starttls':
                smtp.starttls(context=ssl.create_default_context())
            if settings.smtp_user:
                smtp.login(settings.smtp_user, settings.smtp_password)
            smtp.send_message(message)
    elif settings.app_env != 'production':
        folder = Path(settings.data_dir) / 'mail-outbox'
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / (message_id + '.eml')
        # The same delivery identity is safe to retry in the private spool.
        try:
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            return
        with os.fdopen(fd, 'w') as file:
            file.write(message.as_string())
    else:
        raise RuntimeError('smtp_not_configured')


def process_outbox(limit=4):
    delivered = 0
    for _ in range(limit):
        with session_scope(write=True) as db:
            row = db.scalar(select(EmailOutbox).where(
                EmailOutbox.state.in_(['pending', 'sending']),
                EmailOutbox.next_attempt_at <= now()).order_by(
                    EmailOutbox.created_at, EmailOutbox.id).limit(1).with_for_update(skip_locked=True))
            if row is None:
                break
            row.state, row.lease_token = 'sending', uid()
            row.attempts += 1
            row.next_attempt_at = now() + timedelta(minutes=3)
            identity, lease, attempt = row.id, row.lease_token, row.attempts
            recipient, subject, encrypted = row.recipient, row.subject, row.encrypted_payload
        try:
            payload=json.loads(decrypt(encrypted))
            deliver_message(recipient, subject, payload, identity)
        except Exception:
            # Provider exception messages may contain addresses/credentials. Store a category only.
            values = {'state': 'failed' if attempt >= settings.email_max_attempts else 'pending',
                      'error_code': 'delivery_failed', 'lease_token': None,
                      'next_attempt_at': now() + timedelta(seconds=min(3600, 30 * 2 ** min(attempt - 1, 7)))}
        else:
            values = {'state': 'sent', 'sent_at': now(), 'error_code': None, 'lease_token': None}
        with session_scope(write=True) as db:
            changed = db.execute(update(EmailOutbox).where(EmailOutbox.id == identity,
                       EmailOutbox.lease_token == lease).values(**values))
            if values['state'] == 'sent' and changed.rowcount:
                if payload.get('invoice_id') and payload.get('attachments'):
                    from .models import InvoiceDelivery
                    db.execute(update(InvoiceDelivery).where(InvoiceDelivery.invoice_id==payload['invoice_id'],
                        InvoiceDelivery.workspace_id==payload['attachments'][0]['workspace_id']).values(emailed_at=now()))
                delivered += 1
    return delivered
