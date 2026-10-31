"""Private object storage. All keys are workspace-prefixed; authorization is API-owned."""
from pathlib import Path
from typing import Protocol
import hashlib
import os
import tempfile
from .config import settings


class ObjectStore(Protocol):
    def put(self, workspace_id: str, category: str, body: bytes, content_type: str) -> str: ...
    def get(self, workspace_id: str, key: str) -> bytes: ...
    def delete(self, workspace_id: str, key: str) -> None: ...


def validate_key(workspace_id: str, key: str):
    if not key.startswith(workspace_id + "/") or ".." in Path(key).parts or key.startswith("/"):
        raise PermissionError("Object key is outside the authenticated workspace")


def object_key(workspace_id, category, body):
    if category not in {"documents", "snapshots", "recordings", "exports", "logos",'invoices'}:
        raise ValueError("Unsupported object category")
    return f"{workspace_id}/{category}/{hashlib.sha256(body).hexdigest()}"


def put_checked(workspace_id,category,body,content_type):
    """Commit byte reservation before external I/O; ambiguous writes retain it.

    Call outside another write transaction. Accounting is independent of later
    parsing/agent creation, so abandoned objects cannot evade the storage cap.
    """
    from sqlalchemy import select
    from .db import session_scope,uid
    from .models import BudgetAdmission,StoredObjectMeter,Workspace,StorageInventoryState
    from .admission import reserve,finish
    from .metering import stored
    key=object_key(workspace_id,category,body)
    with session_scope(write=True) as db:
        db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
        if settings.app_env=='production' and not db.scalar(select(StorageInventoryState.id).where(StorageInventoryState.workspace_id==workspace_id)):
            from fastapi import HTTPException
            raise HTTPException(503,'Storage inventory requires reconciliation before more files can be stored')
        active=db.scalar(select(StoredObjectMeter).where(StoredObjectMeter.workspace_id==workspace_id,
            StoredObjectMeter.object_key==key,StoredObjectMeter.state=='active'))
        held=db.scalar(select(BudgetAdmission).where(BudgetAdmission.workspace_id==workspace_id,
            BudgetAdmission.kind=='storage',BudgetAdmission.scope_id==key,BudgetAdmission.state.in_(['held','unknown'])))
        operation_key='storage-put:'+key+':'+uid()
        if held:operation_key=None
        elif not active:reserve(db,workspace_id,operation_key,kind='storage',resources={'storage_bytes':len(body)},scope_id=key)
    try:result=get_store().put(workspace_id,category,body,content_type)
    except BaseException:
        with session_scope(write=True) as db:
            for pending in db.scalars(select(BudgetAdmission).where(BudgetAdmission.workspace_id==workspace_id,
                BudgetAdmission.kind=='storage',BudgetAdmission.scope_id==key,BudgetAdmission.state=='held')):
                pending.state='unknown'
        raise
    if result!=key:raise ValueError('Object provider changed content identity')
    with session_scope(write=True) as db:
        stored(db,workspace_id,key,len(body))
        if operation_key:finish(db,workspace_id,operation_key)
        for pending in db.scalars(select(BudgetAdmission).where(BudgetAdmission.workspace_id==workspace_id,
            BudgetAdmission.kind=='storage',BudgetAdmission.scope_id==key,BudgetAdmission.state.in_(['held','unknown']))):
            pending.state='completed'
            from .db import now
            pending.settled_at=now()
    return key


class LocalObjectStore:
    """Explicit development/test fallback; never a production storage choice."""
    def __init__(self, root=None):
        self.root = Path(root or Path(settings.data_dir) / "objects")
        self.root.mkdir(parents=True, exist_ok=True)

    def put(self, workspace_id, category, body, content_type):
        key = object_key(workspace_id, category, body)
        validate_key(workspace_id, key)
        target = self.root / key
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(dir=target.parent)
        try:
            with os.fdopen(fd, "wb") as file:
                file.write(body)
            os.replace(temporary, target)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return key

    def get(self, workspace_id, key):
        validate_key(workspace_id, key)
        return (self.root / key).read_bytes()

    def delete(self, workspace_id, key):
        validate_key(workspace_id, key)
        (self.root / key).unlink(missing_ok=True)

    def inventory(self,workspace_id):
        validate_key(workspace_id,workspace_id+'/documents/inventory')
        for path in (self.root/workspace_id).rglob('*'):
            if path.is_file() and not path.is_symlink():
                yield path.relative_to(self.root).as_posix(),path.stat().st_size


class AzureBlobObjectStore:
    def __init__(self, client=None):
        from azure.storage.blob import BlobServiceClient
        from azure.identity import DefaultAzureCredential
        if client is None:
            if settings.azure_storage_connection_string:
                client = BlobServiceClient.from_connection_string(settings.azure_storage_connection_string)
            elif settings.azure_storage_account_url:
                client = BlobServiceClient(settings.azure_storage_account_url, credential=DefaultAzureCredential())
            else:
                raise RuntimeError("Configure Azure account URL/managed identity or a connection string")
        self.container = client.get_container_client(settings.azure_storage_container)
        self.prefix=settings.azure_storage_prefix.strip('/')
        if self.prefix and any(x in {'','.','..'} for x in self.prefix.split('/')):
            raise ValueError('Azure object prefix must contain ordinary relative path segments')
        # Container provisioning and private-access policy belong to infrastructure, not request handling.

    def put(self, workspace_id, category, body, content_type):
        from azure.storage.blob import ContentSettings
        key = object_key(workspace_id, category, body)
        validate_key(workspace_id, key)
        from azure.core.exceptions import ResourceExistsError
        try:
            # Content-addressed objects are immutable. Overwriting identical blobs
            # can create chargeable versions when account versioning is enabled.
            self.container.upload_blob((self.prefix+'/' if self.prefix else '')+key, body, overwrite=False, content_settings=ContentSettings(content_type=content_type))
        except ResourceExistsError:
            pass
        return key

    def get(self, workspace_id, key):
        validate_key(workspace_id, key)
        return self.container.download_blob((self.prefix+'/' if self.prefix else '')+key).readall()

    def delete(self, workspace_id, key):
        from azure.core.exceptions import ResourceNotFoundError
        validate_key(workspace_id, key)
        try:
            self.container.delete_blob((self.prefix+'/' if self.prefix else '')+key)
        except ResourceNotFoundError:
            pass

    def inventory(self,workspace_id):
        validate_key(workspace_id,workspace_id+'/documents/inventory')
        prefix=self.prefix+'/' if self.prefix else ''
        for blob in self.container.list_blobs(name_starts_with=prefix+workspace_id+'/',results_per_page=500):
            key=blob.name[len(prefix):];validate_key(workspace_id,key)
            yield key,int(blob.size)


def reconcile(workspace_id,*,apply=False,max_objects=100000):
    """Backfill known stored bytes, including orphan/legacy objects. Never deletes.

    Partial scans cannot prove absence, so missing/unknown writes keep their hold.
    Provider inventory is paginated; application memory and work are bounded.
    """
    from sqlalchemy import select
    from .db import session_scope,now
    from .models import Workspace,StoredObjectMeter,BudgetAdmission,StorageInventoryState
    from .metering import stored
    count=total=untracked=scanned=0
    for key,size in get_store().inventory(workspace_id):
        scanned+=1
        if scanned>max_objects:raise RuntimeError('Inventory exceeds scan budget; increase --max-objects and retry')
        # Required financial documents are platform overhead, outside the
        # customer's file allowance. Backups still inventory all categories.
        if key.startswith(workspace_id+'/invoices/'):continue
        count+=1
        if type(size) is not int or size<0:raise ValueError('Invalid storage inventory size')
        total+=size
        with session_scope(write=apply) as db:
            if db.get(Workspace,workspace_id) is None:raise ValueError('Workspace unavailable')
            row=db.scalar(select(StoredObjectMeter).where(StoredObjectMeter.workspace_id==workspace_id,StoredObjectMeter.object_key==key))
            if not row or row.state!='active':untracked+=1
            if apply:
                db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update())
                stored(db,workspace_id,key,size)
                for held in db.scalars(select(BudgetAdmission).where(BudgetAdmission.workspace_id==workspace_id,
                    BudgetAdmission.kind=='storage',BudgetAdmission.scope_id==key,BudgetAdmission.state.in_(['held','unknown']))):
                    held.state='completed';held.settled_at=now()
    if apply:
        with session_scope(write=True) as db:
            if db.scalar(select(Workspace).where(Workspace.id==workspace_id).with_for_update()) is None:raise ValueError('Workspace unavailable')
            state=db.scalar(select(StorageInventoryState).where(StorageInventoryState.workspace_id==workspace_id))
            if state:state.completed_at=now()
            else:db.add(StorageInventoryState(workspace_id=workspace_id,completed_at=now()))
    return {'objects':count,'bytes':total,'untracked_objects':untracked,'applied':apply}


_store = None


def get_store():
    global _store
    if _store is None:
        if settings.object_storage_provider == "azure":
            _store = AzureBlobObjectStore()
        elif settings.object_storage_provider == "local" and settings.app_env != "production":
            _store = LocalObjectStore()
        else:
            raise RuntimeError("Unsupported object storage configuration")
    return _store
