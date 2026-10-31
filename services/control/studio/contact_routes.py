"""Tenant-owned calling contacts with previewed imports and explicit consent."""
import csv
import io
import json
import re
from typing import Literal
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from fastapi.responses import Response
from pydantic import Field, ValidationError, field_validator, model_validator
from sqlalchemy import select, func, or_
from .models import Contact, Campaign, Workspace
from .db import as_dict
from .schemas import Input
from .domain import owned
from .security import principal, db_dependency, audit
from .resource_routes import csv_cell

router = APIRouter(prefix='/v1/workspaces/{workspace_id}')


class ContactWrite(Input):
    name: str = Field(default='', max_length=160)
    phone: str = Field(max_length=40)
    email: str = Field(default='', max_length=254)
    variables: dict[str, str] = Field(default_factory=dict, max_length=30)
    consent: Literal['unknown', 'granted', 'revoked'] = 'unknown'
    consent_note: str = Field(default='', max_length=500)

    @field_validator('phone')
    @classmethod
    def phone_valid(cls, value):
        value = re.sub(r'[\s()\-]', '', value)
        if not re.fullmatch(r'\+[1-9][0-9]{6,14}', value):
            raise ValueError('Use a +country-code phone number')
        return value

    @field_validator('email')
    @classmethod
    def email_valid(cls, value):
        if value:
            from .schemas import Signup
            return Signup.email_valid(value)
        return value

    @field_validator('variables')
    @classmethod
    def variables_valid(cls, value):
        if any(not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', key) or len(item) > 2000 for key, item in value.items()):
            raise ValueError('Use variable names and values shorter than 2000 characters')
        return value

    @model_validator(mode='after')
    def consent_valid(self):
        if self.consent == 'granted' and not self.consent_note:
            raise ValueError('Record how permission to call was obtained')
        return self


class ImportContacts(Input):
    contacts: list[dict] = Field(max_length=1000)
    dry_run: bool = True


class SelectContacts(Input):
    contact_ids: list[str] = Field(min_length=1, max_length=1000)


def import_contacts(db, actor, workspace_id, rows, dry_run):
    parsed, seen, errors, duplicates = [], set(), [], 0
    for index, row in enumerate(rows):
        try:
            contact = ContactWrite.model_validate(row)
        except ValidationError as exc:
            errors.append({'row': index + 1, 'message': '; '.join(e['msg'] for e in exc.errors())[:400]})
            continue
        if contact.phone in seen:
            duplicates += 1
            continue
        seen.add(contact.phone)
        parsed.append(contact)
    if not dry_run and errors:
        raise HTTPException(422, {'message': 'Fix the import errors before saving. No contacts were changed.', 'errors': errors})
    if not dry_run:
        db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
    existing = {row.phone: row for row in db.scalars(select(Contact).where(Contact.workspace_id == workspace_id,
                        Contact.phone.in_([r.phone for r in parsed])))}
    if not dry_run:
        db.scalar(select(Workspace).where(Workspace.id == workspace_id).with_for_update())
        for contact in parsed:
            if contact.phone in existing:
                target = existing[contact.phone]
                # Reimport never silently restores permission that was revoked.
                values = contact.model_dump()
                if target.consent == 'revoked' or contact.consent == 'unknown':
                    values.pop('consent'); values.pop('consent_note')
                for key, value in values.items():
                    if value not in ('', {}):
                        setattr(target, key, value)
            else:
                db.add(Contact(workspace_id=workspace_id, **contact.model_dump()))
        audit(db, actor, 'contacts.imported', data={'count': len(parsed)})
    return {'accepted': len(parsed), 'duplicates': duplicates, 'existing': len(existing), 'errors': errors,
            'dry_run': dry_run, 'preview': [p.model_dump() for p in parsed[:25]]}


@router.get('/contacts')
def contacts(workspace_id: str, search: str = '', offset: int = 0, limit: int = 50,
             actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('leads:read')
    if offset < 0 or limit not in range(1, 201) or len(search) > 200:
        raise HTTPException(422, 'Invalid contact page')
    query = select(Contact).where(Contact.workspace_id == workspace_id, Contact.archived.is_(False))
    if search:
        query = query.where(or_(Contact.name.ilike('%' + search + '%'), Contact.phone.ilike('%' + search + '%'), Contact.email.ilike('%' + search + '%')))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    return {'items': [as_dict(r) for r in db.scalars(query.order_by(Contact.created_at.desc()).offset(offset).limit(limit))],
            'total': total, 'offset': offset, 'limit': limit}


@router.post('/contacts/import')
def import_json(workspace_id: str, body: ImportContacts, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('leads:write')
    return import_contacts(db, actor, workspace_id, body.contacts, body.dry_run)


@router.post('/contacts/import.csv')
async def import_csv(workspace_id: str, dry_run: bool = True, file: UploadFile = File(...), actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('leads:write')
    raw = await file.read(2_000_001)
    if len(raw) > 2_000_000:
        raise HTTPException(413, 'CSV files must be smaller than 2 MB')
    try:
        reader = csv.DictReader(io.StringIO(raw.decode('utf-8-sig')))
        allowed = {'name', 'phone', 'email', 'variables', 'consent', 'consent_note'}
        if not reader.fieldnames or 'phone' not in reader.fieldnames or set(reader.fieldnames) - allowed or len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError()
        rows = []
        for row in reader:
            if len(rows) >= 1000 or None in row:
                raise ValueError()
            row = {key: value for key, value in row.items() if value is not None and value.strip()}
            if 'variables' in row:
                row['variables'] = json.loads(row['variables'])
            rows.append(row)
    except (UnicodeError, ValueError, csv.Error):
        raise HTTPException(422, 'Use a UTF-8 CSV with phone,name,email,consent,consent_note,variables columns and at most 1000 rows. Variables use a JSON object.')
    return import_contacts(db, actor, workspace_id, rows, dry_run)


@router.get('/contacts/export.csv')
def export_contacts(workspace_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('leads:read')
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(['name', 'phone', 'email', 'consent', 'consent_note', 'variables'])
    for row in db.scalars(select(Contact).where(Contact.workspace_id == workspace_id, Contact.archived.is_(False)).limit(10000)):
        writer.writerow([csv_cell(row.name), row.phone, csv_cell(row.email), row.consent,
                         csv_cell(row.consent_note), csv_cell(json.dumps(row.variables))])
    audit(db, actor, 'contacts.exported')
    return Response('\ufeff' + output.getvalue(), media_type='text/csv; charset=utf-8',
                    headers={'Content-Disposition': 'attachment; filename="contacts.csv"'})


@router.put('/contacts/{contact_id}')
def update_contact(workspace_id: str, contact_id: str, body: ContactWrite, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('leads:write')
    row = owned(db, Contact, workspace_id, contact_id)
    conflict = db.scalar(select(Contact.id).where(Contact.workspace_id == workspace_id, Contact.phone == body.phone, Contact.id != row.id))
    if conflict:
        raise HTTPException(409, 'Another contact already has this number')
    for key, value in body.model_dump().items():
        setattr(row, key, value)
    audit(db, actor, 'contact.updated', row.id)
    return as_dict(row)


@router.delete('/contacts/{contact_id}')
def archive_contact(workspace_id: str, contact_id: str, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('leads:write')
    row = owned(db, Contact, workspace_id, contact_id)
    row.archived = True
    audit(db, actor, 'contact.archived', row.id)
    return {'status': 'archived'}


@router.post('/campaigns/{campaign_id}/contacts/from-addressbook')
def campaign_contacts(workspace_id: str, campaign_id: str, body: SelectContacts, actor=Depends(principal), db=Depends(db_dependency, scope='function')):
    actor.require('campaigns:write'); actor.require('leads:read')
    campaign = owned(db, Campaign, workspace_id, campaign_id)
    if campaign.state != 'draft':
        raise HTTPException(409, 'Contacts can only change on a draft campaign')
    rows = [owned(db, Contact, workspace_id, contact_id) for contact_id in dict.fromkeys(body.contact_ids)]
    if any(row.archived or row.consent != 'granted' for row in rows):
        raise HTTPException(409, 'Select active contacts with permission to call')
    campaign.contacts = [{'contact_id': r.id, 'phone': r.phone, 'name': r.name, 'variables': r.variables,
                          'consent_confirmed': True} for r in rows]
    return {'accepted': len(rows)}
