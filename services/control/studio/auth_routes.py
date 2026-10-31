from fastapi import APIRouter, Depends, Request, Response, HTTPException
from sqlalchemy import select, func
from sqlalchemy.exc import IntegrityError
from .db import as_dict
from .models import *
from .schemas import Signup, Signin, WorkspaceWrite
from .security import db_dependency, active_user, check_origin, new_session, password_hash, password_matches, limiter, digest
from .domain import post_ledger
from .config import settings
from .sessions import public_user, clear_cookies, refresh_session
from .account_policy import require_verified, verification_required, uniform_auth_response

router = APIRouter(prefix="/v1")


def create_workspace(db, user, name, timezone="Asia/Kolkata", currency="INR"):
    db.scalar(select(User).where(User.id == user.id).with_for_update())
    require_verified(db, user)
    count = db.scalar(select(func.count()).select_from(Membership).where(
        Membership.user_id == user.id, Membership.role == 'owner'))
    if count >= settings.max_owned_workspaces:
        raise HTTPException(409, 'Workspace creation limit reached')
    workspace = Workspace(name=name, timezone=timezone, currency=currency, free_allowance_user_id=user.id)
    db.add(workspace)
    db.flush()
    db.add(Membership(workspace_id=workspace.id, user_id=user.id, role="owner"))
    db.add(Wallet(workspace_id=workspace.id, currency=currency, balance_minor=0))
    db.add(StorageInventoryState(workspace_id=workspace.id))
    db.flush()
    if settings.dev_seed_enabled and settings.app_env != "production":
        post_ledger(db, workspace.id, 10000, "development-initial-credit", "Development credit — not purchased money")
    for provider, title in [("google_calendar", "Google Calendar"), ("hubspot", "HubSpot"), ("whatsapp", "WhatsApp Business"), ("sms", "SMS sender"), ("mcp", "MCP tools")]:
        db.add(Connection(workspace_id=workspace.id, provider=provider, name=title, state="disconnected"))
    return workspace


@router.post("/auth/signup", status_code=202)
def signup(body: Signup, request: Request, response: Response, db=Depends(db_dependency, scope="function")):
    check_origin(request)
    limiter.check("signup:" + (request.client.host if request.client else "local"), 10, 3600)
    limiter.check('signup-email:' + digest(body.email), 3, 3600)
    from . import legal
    policy = legal.validate(body.legal_accepted, body.legal_version)
    with uniform_auth_response():
        encoded = password_hash(body.password)  # Same expensive work for existing emails.
        user = db.scalar(select(User).where(User.email == body.email).with_for_update())
        created = False
        if user is None:
            try:
                with db.begin_nested():
                    user = User(email=body.email, name=body.name, password_hash=encoded)
                    db.add(user)
                    db.flush()
                created = True
            except IntegrityError:
                user = db.scalar(select(User).where(User.email == body.email).with_for_update())
        if created:
            legal.record(db, user.id, legal.evidence(request, policy), source='password_signup')
        if created and verification_required():
            db.add(PendingRegistration(user_id=user.id, workspace_name=body.workspace_name))
            from .identity_routes import send_verification
            send_verification(db, user)
        else:
            if created:
                create_workspace(db, user, body.workspace_name)
            from .account_routes import send_account_email
            send_account_email(body.email, 'Your Phirmy sign-in', settings.app_origin + '/signin', db=db)
        # Never authenticate, expose IDs or change an existing password on signup.
        return {'message': 'If this address can register, check your inbox to continue. Otherwise sign in.',
                'verification_required': verification_required()}


@router.post("/auth/signin")
def signin(body: Signin, request: Request, response: Response, db=Depends(db_dependency, scope="function")):
    check_origin(request)
    limiter.check("signin:" + (request.client.host if request.client else "local"), 30, 300)
    limiter.check("signin-email:" + digest(body.email.strip().casefold()), 10, 900)
    user = db.scalar(select(User).where(User.email == body.email.lower()))
    from .security import DUMMY_PASSWORD_HASH
    matches = password_matches(body.password, user.password_hash if user else DUMMY_PASSWORD_HASH)
    if not user or not matches:
        raise HTTPException(401, "Email or password is incorrect")
    new_session(db, user, response, request)
    return {"user": public_user(db, user)}


@router.get("/auth/me")
def me(request: Request, db=Depends(db_dependency, scope="function")):
    user = active_user(request, db)
    memberships = list(db.scalars(select(Membership).where(Membership.user_id == user.id)))
    return {"user": public_user(db, user),
            "workspaces": [{**as_dict(db.get(Workspace, x.workspace_id)), "role": x.role} for x in memberships]}


@router.post("/auth/signout")
def signout(request: Request, response: Response, db=Depends(db_dependency, scope="function")):
    active_user(request, db)
    session = db.get(AuthSession, request.state.auth_session_id)
    if session:
        db.delete(session)
    clear_cookies(response)
    return {"status": "signed_out"}


@router.post('/auth/refresh')
def refresh(request: Request, response: Response, db=Depends(db_dependency, scope='function')):
    return refresh_session(request, response, db)


@router.post("/workspaces", status_code=201)
def workspace_create(body: WorkspaceWrite, request: Request, db=Depends(db_dependency, scope="function")):
    from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
    user = active_user(request, db)
    require_verified(db, user)
    try:
        ZoneInfo(body.timezone)
    except ZoneInfoNotFoundError:
        raise HTTPException(422, "Use a valid IANA timezone")
    return as_dict(create_workspace(db, user, body.name, body.timezone, body.currency))
