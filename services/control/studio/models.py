from datetime import datetime
from sqlalchemy import String, Text, JSON, Integer, BigInteger,Boolean, DateTime, ForeignKey, UniqueConstraint, CheckConstraint, ForeignKeyConstraint
from sqlalchemy.orm import Mapped, mapped_column
from .db import Base, Entity, Tenant, now, tenant_unique, UTCDateTime


class User(Entity, Base):
    __tablename__ = "users"
    email: Mapped[str] = mapped_column(String(254), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    password_hash: Mapped[str] = mapped_column(Text)


class LegalPolicySnapshot(Entity, Base):
    __tablename__ = 'legal_policy_snapshots'
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    content: Mapped[dict] = mapped_column(JSON)


class LegalAcceptance(Entity, Base):
    __tablename__ = 'legal_acceptances'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), index=True)
    policy_id: Mapped[str] = mapped_column(ForeignKey('legal_policy_snapshots.id'))
    accepted_at: Mapped[datetime] = mapped_column(UTCDateTime())
    ip_hash: Mapped[str] = mapped_column(String(64))
    source: Mapped[str] = mapped_column(String(30))
    __table_args__ = (UniqueConstraint('user_id', 'policy_id'),)


class PendingRegistration(Entity, Base):
    __tablename__ = 'pending_registrations'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), unique=True)
    workspace_name: Mapped[str] = mapped_column(String(120))


class EmailOutbox(Entity, Base):
    __tablename__ = 'email_outbox'
    operation_key: Mapped[str] = mapped_column(String(200), unique=True)
    recipient: Mapped[str] = mapped_column(String(254))
    subject: Mapped[str] = mapped_column(String(200))
    encrypted_payload: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default='pending', index=True)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now, index=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40), nullable=True)


class WorkerHeartbeat(Entity, Base):
    __tablename__ = 'worker_heartbeats'
    group: Mapped[str] = mapped_column(String(80), index=True)
    state: Mapped[str] = mapped_column(String(20), default='active')
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now, index=True)


class OriginVerification(Tenant, Base):
    __tablename__ = 'origin_verifications'
    origin: Mapped[str] = mapped_column(String(512))
    encrypted_token: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    verified_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    method: Mapped[str | None] = mapped_column(String(20), nullable=True)
    __table_args__ = (tenant_unique(), UniqueConstraint('workspace_id', 'origin'))


class ToolBudget(Tenant, Base):
    __tablename__ = 'tool_budgets'
    scope_key: Mapped[str] = mapped_column(String(100))
    calls_used: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (tenant_unique(), UniqueConstraint('workspace_id', 'scope_key'))


class ToolAttempt(Tenant, Base):
    __tablename__ = 'tool_attempts'
    scope_key: Mapped[str] = mapped_column(String(100))
    operation_key: Mapped[str] = mapped_column(String(64))
    tool_name: Mapped[str] = mapped_column(String(100))
    __table_args__ = (tenant_unique(), UniqueConstraint('workspace_id', 'scope_key', 'operation_key'))


class ToolConsent(Tenant, Base):
    __tablename__ = 'tool_consents'
    scope_key: Mapped[str] = mapped_column(String(100), index=True)
    tool_name: Mapped[str] = mapped_column(String(100))
    args_hash: Mapped[str] = mapped_column(String(64))
    encrypted_payload: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default='pending')
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    presented_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    encrypted_result: Mapped[str | None] = mapped_column(Text, nullable=True)


class SchemaMigration(Entity, Base):
    __tablename__ = 'schema_migrations'
    revision: Mapped[str] = mapped_column(String(80), unique=True)


class PlanCatalogSnapshot(Entity, Base):
    __tablename__='plan_catalog_snapshots'
    content_hash: Mapped[str] = mapped_column(String(64),unique=True)
    version: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(20))
    content: Mapped[dict] = mapped_column(JSON)


class WorkspaceSubscription(Tenant, Base):
    __tablename__='workspace_subscriptions'
    catalog_id: Mapped[str] = mapped_column(ForeignKey('plan_catalog_snapshots.id'))
    plan_slug: Mapped[str] = mapped_column(String(40),default='free')
    state: Mapped[str] = mapped_column(String(30),default='free')
    period_start: Mapped[datetime] = mapped_column(UTCDateTime())
    period_end: Mapped[datetime] = mapped_column(UTCDateTime())
    provider_subscription_id: Mapped[str | None] = mapped_column(String(100),nullable=True,unique=True)
    provider_customer_id: Mapped[str | None] = mapped_column(String(100),nullable=True)
    pending_plan_slug: Mapped[str | None] = mapped_column(String(40),nullable=True)
    spend_cap_minor: Mapped[int | None] = mapped_column(BigInteger,nullable=True)
    operator_paused: Mapped[bool] = mapped_column(Boolean,default=False)
    billing_blocked: Mapped[bool] = mapped_column(Boolean,default=False)
    maintenance_at: Mapped[datetime | None] = mapped_column(UTCDateTime(),nullable=True)
    failed_payments: Mapped[int] = mapped_column(Integer,default=0)
    dunning_at: Mapped[datetime | None] = mapped_column(UTCDateTime(),nullable=True)
    billing_profile: Mapped[dict] = mapped_column(JSON,default=dict)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id'),)


class TariffSnapshot(Tenant, Base):
    __tablename__='tariff_snapshots'
    catalog_id: Mapped[str] = mapped_column(ForeignKey('plan_catalog_snapshots.id'))
    operation_key: Mapped[str] = mapped_column(String(64))
    call_id: Mapped[str | None] = mapped_column(String(36),nullable=True,index=True)
    content: Mapped[dict] = mapped_column(JSON)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','operation_key'))


class MeterEvent(Tenant, Base):
    __tablename__='meter_events'
    operation_key: Mapped[str] = mapped_column(String(64))
    resource: Mapped[str] = mapped_column(String(40),index=True)
    quantity: Mapped[int] = mapped_column(BigInteger)
    direction: Mapped[str] = mapped_column(String(12),default='consume')
    scope_id: Mapped[str | None] = mapped_column(String(100),nullable=True)
    tariff_id: Mapped[str | None] = mapped_column(String(36),nullable=True)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','operation_key'),CheckConstraint('quantity >= 0'))


class CallCostRecord(Tenant, Base):
    __tablename__='call_cost_records'
    operation_key: Mapped[str] = mapped_column(String(64))
    call_id: Mapped[str | None] = mapped_column(String(36),nullable=True,index=True)
    tariff_id: Mapped[str] = mapped_column(String(36))
    provider: Mapped[str] = mapped_column(String(40))
    model: Mapped[str | None] = mapped_column(String(160),nullable=True)
    stage: Mapped[str] = mapped_column(String(40))
    units: Mapped[dict] = mapped_column(JSON)
    cost_micro_minor: Mapped[int] = mapped_column(BigInteger)
    source: Mapped[str] = mapped_column(String(40))
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','operation_key'),CheckConstraint('cost_micro_minor >= 0'))


class StoredObjectMeter(Tenant, Base):
    __tablename__='stored_object_meter'
    object_key: Mapped[str] = mapped_column(String(200))
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    state: Mapped[str] = mapped_column(String(20),default='active')
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(),nullable=True)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','object_key'))


class BudgetAdmission(Tenant, Base):
    __tablename__='budget_admissions'
    operation_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(30))
    scope_id: Mapped[str | None] = mapped_column(String(200),nullable=True,index=True)
    installation_id: Mapped[str | None] = mapped_column(String(36),nullable=True,index=True)
    tariff_id: Mapped[str] = mapped_column(String(36))
    resources: Mapped[dict] = mapped_column(JSON,default=dict)
    reserved_micro_minor: Mapped[int] = mapped_column(BigInteger,default=0)
    measured_micro_minor: Mapped[int] = mapped_column(BigInteger,default=0)
    state: Mapped[str] = mapped_column(String(20),default='held')
    settled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(),nullable=True)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','operation_key'),
                   CheckConstraint('reserved_micro_minor >= 0'))


class StorageInventoryState(Tenant, Base):
    __tablename__='storage_inventory_states'
    completed_at: Mapped[datetime] = mapped_column(UTCDateTime(),default=now)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id'),)


class CipherRotationJob(Entity, Base):
    __tablename__='cipher_rotation_jobs'
    workspace_id: Mapped[str | None] = mapped_column(ForeignKey('workspaces.id'),nullable=True)
    target_key_id: Mapped[str] = mapped_column(String(64))
    requested_by: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(20),default='queued',index=True)
    cursor: Mapped[dict] = mapped_column(JSON,default=dict)
    tables: Mapped[list] = mapped_column(JSON)
    scanned: Mapped[int] = mapped_column(Integer,default=0)
    rotated: Mapped[int] = mapped_column(Integer,default=0)
    lease_token: Mapped[str | None] = mapped_column(String(36),nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime(),nullable=True)
    error: Mapped[dict] = mapped_column(JSON,default=dict)


class CipherRotationAudit(Entity, Base):
    __tablename__='cipher_rotation_audit'
    job_id: Mapped[str] = mapped_column(ForeignKey('cipher_rotation_jobs.id'))
    event: Mapped[str] = mapped_column(String(30))
    data: Mapped[dict] = mapped_column(JSON,default=dict)


class WidgetProtection(Tenant, Base):
    __tablename__='widget_protection'
    installation_id: Mapped[str] = mapped_column(String(36))
    policy: Mapped[dict] = mapped_column(JSON,default=dict)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','installation_id'),
        ForeignKeyConstraint(['workspace_id','installation_id'],['widget_installations.workspace_id','widget_installations.id']))


class WidgetBucket(Tenant, Base):
    __tablename__='widget_buckets'
    installation_id: Mapped[str] = mapped_column(String(36))
    period: Mapped[str] = mapped_column(String(20))
    sessions: Mapped[int] = mapped_column(Integer,default=0)
    turns: Mapped[int] = mapped_column(Integer,default=0)
    reserved_minor: Mapped[int] = mapped_column(Integer,default=0)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','installation_id','period'),
        ForeignKeyConstraint(['workspace_id','installation_id'],['widget_installations.workspace_id','widget_installations.id']))


class WidgetIPBucket(Entity, Base):
    __tablename__='widget_ip_buckets'
    ip_hash: Mapped[str] = mapped_column(String(64))
    period: Mapped[str] = mapped_column(String(20))
    kind: Mapped[str] = mapped_column(String(20))
    amount: Mapped[int] = mapped_column(Integer,default=0)
    __table_args__=(UniqueConstraint('ip_hash','period','kind'),)


class WidgetAdmission(Tenant, Base):
    __tablename__='widget_admissions'
    installation_id: Mapped[str] = mapped_column(String(36))
    operation_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    reserved_minor: Mapped[int] = mapped_column(Integer)
    rate_status: Mapped[str] = mapped_column(String(20),default='DRAFT')
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','operation_key'),
        ForeignKeyConstraint(['workspace_id','installation_id'],['widget_installations.workspace_id','widget_installations.id']))


class WidgetEmailChallenge(Tenant, Base):
    __tablename__='widget_email_challenges'
    conversation_id: Mapped[str] = mapped_column(String(36))
    encrypted_email: Mapped[str] = mapped_column(Text)
    email_hash: Mapped[str] = mapped_column(String(64))
    code_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    attempts: Mapped[int] = mapped_column(Integer,default=0)
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(),nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(),nullable=True)
    lead_id: Mapped[str | None] = mapped_column(String(36),nullable=True)
    __table_args__=(tenant_unique(),
        ForeignKeyConstraint(['workspace_id','conversation_id'],['conversations.workspace_id','conversations.id']),
        ForeignKeyConstraint(['workspace_id','lead_id'],['leads.workspace_id','leads.id']))


class WidgetMarketingConsent(Tenant, Base):
    __tablename__='widget_marketing_consents'
    challenge_id: Mapped[str] = mapped_column(String(36),unique=True)
    lead_id: Mapped[str] = mapped_column(String(36))
    email_hash: Mapped[str] = mapped_column(String(64))
    origin: Mapped[str] = mapped_column(String(512))
    ip_hash: Mapped[str] = mapped_column(String(64))
    text_version: Mapped[str] = mapped_column(String(40))
    text_content: Mapped[str] = mapped_column(Text)
    __table_args__=(tenant_unique(),
        ForeignKeyConstraint(['workspace_id','challenge_id'],['widget_email_challenges.workspace_id','widget_email_challenges.id']),
        ForeignKeyConstraint(['workspace_id','lead_id'],['leads.workspace_id','leads.id']))


class Workspace(Entity, Base):
    __tablename__ = "workspaces"
    free_allowance_user_id: Mapped[str | None] = mapped_column(ForeignKey('users.id'), nullable=True, index=True)
    name: Mapped[str] = mapped_column(String(120))
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Kolkata")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    settings_data: Mapped[dict] = mapped_column(JSON, default=dict)


class Membership(Tenant, Base):
    __tablename__ = "memberships"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    role: Mapped[str] = mapped_column(String(20), default="owner")
    __table_args__ = (UniqueConstraint("workspace_id", "user_id"), tenant_unique())


class AuthSession(Entity, Base):
    __tablename__ = "auth_sessions"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())


class UserProfile(Entity, Base):
    __tablename__ = 'user_profiles'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'), unique=True)
    email_verified_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    timezone: Mapped[str] = mapped_column(String(80), default='Asia/Kolkata')
    avatar_color: Mapped[str] = mapped_column(String(20), default='sage')
    notifications_enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class SessionInfo(Entity, Base):
    __tablename__ = 'session_details'
    session_id: Mapped[str] = mapped_column(ForeignKey('auth_sessions.id', ondelete='CASCADE'), unique=True)
    user_agent: Mapped[str] = mapped_column(String(300), default='')
    last_seen_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)


class SessionRefresh(Entity, Base):
    __tablename__ = 'session_refresh_tokens'
    session_id: Mapped[str] = mapped_column(ForeignKey('auth_sessions.id', ondelete='CASCADE'), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class OAuthIdentity(Entity, Base):
    __tablename__ = 'oauth_identities'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    provider: Mapped[str] = mapped_column(String(30))
    subject: Mapped[str] = mapped_column(String(255))
    __table_args__ = (UniqueConstraint('provider', 'subject'), UniqueConstraint('user_id', 'provider'))


class OAuthAttempt(Entity, Base):
    __tablename__ = 'oauth_attempts'
    state_hash: Mapped[str] = mapped_column(String(64), unique=True)
    encrypted_data: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Notification(Tenant, Base):
    __tablename__ = 'notifications'
    kind: Mapped[str] = mapped_column(String(80))
    title: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(String(500), default='')
    href: Mapped[str] = mapped_column(String(300), default='/app/operations')
    __table_args__ = (tenant_unique(),)


class NotificationRead(Entity, Base):
    __tablename__ = 'notification_reads'
    notification_id: Mapped[str] = mapped_column(ForeignKey('notifications.id', ondelete='CASCADE'))
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id', ondelete='CASCADE'))
    __table_args__ = (UniqueConstraint('notification_id', 'user_id'),)


class UsageRecord(Tenant, Base):
    __tablename__ = 'workspace_usage'
    operation_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30), default='turn')
    __table_args__ = (tenant_unique(), UniqueConstraint('workspace_id', 'operation_key'))


class PhoneTrialPool(Entity, Base):
    __tablename__ = 'phone_trial_pools'
    name: Mapped[str] = mapped_column(String(120))
    encrypted_credentials: Mapped[str] = mapped_column(Text)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    alert_email: Mapped[str] = mapped_column(String(254))
    max_workspaces: Mapped[int] = mapped_column(Integer, default=10)
    workspaces_issued: Mapped[int] = mapped_column(Integer, default=0)
    calls_per_workspace: Mapped[int] = mapped_column(Integer, default=3)
    seconds_per_call: Mapped[int] = mapped_column(Integer, default=60)
    low_balance_minor: Mapped[int] = mapped_column(Integer, default=200)
    currency: Mapped[str] = mapped_column(String(3), default='USD')
    balance_minor: Mapped[int | None] = mapped_column(Integer, nullable=True)
    balance_checked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    balance_state: Mapped[str] = mapped_column(String(30), default='unknown')


class PhoneTrial(Tenant, Base):
    __tablename__ = 'phone_trials'
    pool_id: Mapped[str] = mapped_column(ForeignKey('phone_trial_pools.id'))
    number_id: Mapped[str] = mapped_column(String(36), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    destinations: Mapped[list] = mapped_column(JSON, default=list)
    calls_used: Mapped[int] = mapped_column(Integer, default=0)
    max_calls: Mapped[int] = mapped_column(Integer, default=3)
    seconds_per_call: Mapped[int] = mapped_column(Integer, default=60)
    __table_args__ = (tenant_unique(), UniqueConstraint('workspace_id'),
                      ForeignKeyConstraint(['workspace_id', 'number_id'], ['phone_numbers.workspace_id', 'phone_numbers.id']))


class PhoneTrialAlert(Entity, Base):
    __tablename__ = 'phone_trial_alerts'
    pool_id: Mapped[str] = mapped_column(ForeignKey('phone_trial_pools.id'))
    operation_key: Mapped[str] = mapped_column(String(200), unique=True)
    subject: Mapped[str] = mapped_column(String(200))
    body: Mapped[str] = mapped_column(Text)
    state: Mapped[str] = mapped_column(String(20), default='pending')
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class PhoneNumberOrder(Tenant, Base):
    __tablename__ = 'phone_number_orders'
    user_id: Mapped[str] = mapped_column(ForeignKey('users.id'), unique=True)
    pool_id: Mapped[str] = mapped_column(ForeignKey('phone_trial_pools.id'))
    state: Mapped[str] = mapped_column(String(30), default='queued')
    e164: Mapped[str | None] = mapped_column(String(20), nullable=True)
    provider_number_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    quoted_price_minor: Mapped[int] = mapped_column(Integer, default=0)
    purchase_reserved: Mapped[bool] = mapped_column(Boolean, default=False)
    purchase_started_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(50), nullable=True)
    __table_args__ = (tenant_unique(), UniqueConstraint('workspace_id'))


class PhoneNumberInventory(Entity, Base):
    __tablename__ = 'phone_number_inventory'
    pool_id: Mapped[str] = mapped_column(ForeignKey('phone_trial_pools.id'))
    e164: Mapped[str] = mapped_column(String(20), unique=True)
    provider_number_id: Mapped[str] = mapped_column(String(100), unique=True)
    assigned_order_id: Mapped[str | None] = mapped_column(ForeignKey('phone_number_orders.id'), nullable=True, unique=True)


class Contact(Tenant, Base):
    __tablename__ = 'contacts'
    name: Mapped[str] = mapped_column(String(160), default='')
    phone: Mapped[str] = mapped_column(String(20))
    email: Mapped[str] = mapped_column(String(254), default='')
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    consent: Mapped[str] = mapped_column(String(20), default='unknown')
    consent_note: Mapped[str] = mapped_column(String(500), default='')
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (tenant_unique(), UniqueConstraint('workspace_id', 'phone'))


class APIKey(Tenant, Base):
    __tablename__ = "api_keys"
    name: Mapped[str] = mapped_column(String(120))
    prefix: Mapped[str] = mapped_column(String(16))
    secret_hash: Mapped[str] = mapped_column(String(64), unique=True)
    scopes: Mapped[list] = mapped_column(JSON)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    expires_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    last_used_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    requests_per_minute: Mapped[int] = mapped_column(Integer, default=60, server_default="60")
    __table_args__ = (tenant_unique(),)


class Audit(Tenant, Base):
    __tablename__ = "audit_events"
    actor_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    action: Mapped[str] = mapped_column(String(100))
    resource_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    data: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (tenant_unique(),)


class Job(Tenant, Base):
    __tablename__ = "jobs"
    kind: Mapped[str] = mapped_column(String(40))
    state: Mapped[str] = mapped_column(String(20), default="queued", index=True)
    phase: Mapped[str] = mapped_column(String(80), default="queued")
    payload: Mapped[dict] = mapped_column(JSON, default=dict)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    completed_items: Mapped[int] = mapped_column(Integer, default=0)
    total_items: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_until: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    lease_token: Mapped[str | None] = mapped_column(String(36), nullable=True)
    available_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True, index=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    __table_args__ = (tenant_unique(),)


class KnowledgeBase(Tenant, Base):
    __tablename__ = "knowledge_bases"
    name: Mapped[str] = mapped_column(String(160))
    website_url: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(20), default="processing")
    priority_guidance: Mapped[str] = mapped_column(Text, default="")
    active_snapshot_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    pages_indexed: Mapped[int] = mapped_column(Integer, default=0)
    chunks_indexed: Mapped[int] = mapped_column(Integer, default=0)
    assessment: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (tenant_unique(),)


class Snapshot(Tenant, Base):
    __tablename__ = "knowledge_snapshots"
    kb_id: Mapped[str] = mapped_column(String(36))
    revision: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="building")
    source_ids: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "kb_id", "revision"),
                      ForeignKeyConstraint(["workspace_id", "kb_id"], ["knowledge_bases.workspace_id", "knowledge_bases.id"]))


class Source(Tenant, Base):
    __tablename__ = "knowledge_sources"
    kb_id: Mapped[str] = mapped_column(String(36))
    canonical_url: Mapped[str] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text, default="")
    text_content: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64))
    raw_object_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="indexed")
    fetched_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "kb_id", "canonical_url", "content_hash"),
                      ForeignKeyConstraint(["workspace_id", "kb_id"], ["knowledge_bases.workspace_id", "knowledge_bases.id"]))


class Chunk(Tenant, Base):
    __tablename__ = "knowledge_chunks"
    source_id: Mapped[str] = mapped_column(String(36))
    ordinal: Mapped[int] = mapped_column(Integer)
    text_content: Mapped[str] = mapped_column(Text)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "source_id", "ordinal"),
                      ForeignKeyConstraint(["workspace_id", "source_id"], ["knowledge_sources.workspace_id", "knowledge_sources.id"]))


class Agent(Tenant, Base):
    __tablename__ = "agents"
    name: Mapped[str] = mapped_column(String(160))
    draft_config: Mapped[dict] = mapped_column(JSON)
    draft_revision: Mapped[int] = mapped_column(Integer, default=1)
    published_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (tenant_unique(),)


class AgentVersion(Tenant, Base):
    __tablename__ = "agent_versions"
    agent_id: Mapped[str] = mapped_column(String(36))
    version: Mapped[int] = mapped_column(Integer)
    config: Mapped[dict] = mapped_column(JSON)
    config_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "agent_id", "version"),
                      ForeignKeyConstraint(["workspace_id", "agent_id"], ["agents.workspace_id", "agents.id"]))


class Number(Tenant, Base):
    __tablename__ = "phone_numbers"
    e164: Mapped[str] = mapped_column(String(20))
    provider: Mapped[str] = mapped_column(String(20))
    provider_number_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    can_inbound: Mapped[bool] = mapped_column(Boolean, default=False)
    can_outbound: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(20), default="unverified")
    agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "e164"), UniqueConstraint("provider", "e164", name="uq_number_provider_e164"),
                      ForeignKeyConstraint(["workspace_id", "agent_id"], ["agents.workspace_id", "agents.id"]))


class Call(Tenant, Base):
    __tablename__ = "calls"
    agent_version_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    agent_name: Mapped[str] = mapped_column(String(160), default="")
    direction: Mapped[str] = mapped_column(String(20), default="inbound")
    transport: Mapped[str] = mapped_column(String(30), default="browser")
    mode: Mapped[str] = mapped_column(String(20), default="simulation")
    state: Mapped[str] = mapped_column(String(20), default="created")
    destination: Mapped[str] = mapped_column(String(20), default="")
    provider_call_id: Mapped[str | None] = mapped_column(String(100), nullable=True, unique=True)
    connected_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    connected_ms: Mapped[int] = mapped_column(Integer, default=0)
    failure_code: Mapped[str | None] = mapped_column(Text, nullable=True)
    analysis: Mapped[dict] = mapped_column(JSON, default=dict)
    metadata_data: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (tenant_unique(), CheckConstraint("connected_ms >= 0"),
                      ForeignKeyConstraint(["workspace_id", "agent_version_id"], ["agent_versions.workspace_id", "agent_versions.id"]))


class VoiceTimingRecord(Tenant, Base):
    __tablename__ = 'voice_timing_records'
    call_id: Mapped[str] = mapped_column(ForeignKey('calls.id', ondelete='CASCADE'), index=True)
    turn_id: Mapped[str] = mapped_column(String(36), unique=True)
    epoch: Mapped[int] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(20))
    input_kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    marks_ms: Mapped[dict] = mapped_column(JSON)
    durations_ms: Mapped[dict] = mapped_column(JSON)


class Turn(Tenant, Base):
    __tablename__ = "transcript_turns"
    call_id: Mapped[str] = mapped_column(String(36))
    ordinal: Mapped[int] = mapped_column(Integer)
    speaker: Mapped[str] = mapped_column(String(20))
    text_content: Mapped[str] = mapped_column(Text)
    interrupted: Mapped[bool] = mapped_column(Boolean, default=False)
    epoch: Mapped[int] = mapped_column(Integer, default=0)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "call_id", "ordinal"),
                      ForeignKeyConstraint(["workspace_id", "call_id"], ["calls.workspace_id", "calls.id"]))


class Wallet(Tenant, Base):
    __tablename__ = "wallets"
    balance_minor: Mapped[int] = mapped_column(Integer, default=0)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id"), CheckConstraint("balance_minor >= 0"))


class Reservation(Tenant, Base):
    __tablename__ = "wallet_reservations"
    call_id: Mapped[str] = mapped_column(String(36))
    amount_minor: Mapped[int] = mapped_column(Integer)
    state: Mapped[str] = mapped_column(String(20), default="active")
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "call_id"), CheckConstraint("amount_minor >= 0"),
                      ForeignKeyConstraint(["workspace_id", "call_id"], ["calls.workspace_id", "calls.id"]))


class Ledger(Tenant, Base):
    __tablename__ = "ledger_entries"
    amount_minor: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(String(30))
    operation_key: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    call_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "operation_key"),
                      ForeignKeyConstraint(["workspace_id", "call_id"], ["calls.workspace_id", "calls.id"]))


class Store(Tenant, Base):
    __tablename__ = "stores"
    name: Mapped[str] = mapped_column(String(160))
    website_url: Mapped[str] = mapped_column(Text)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "website_url"))


class Product(Tenant, Base):
    __tablename__ = "products"
    store_id: Mapped[str] = mapped_column(String(36))
    title: Mapped[str] = mapped_column(String(300))
    canonical_url: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    price_minor: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    availability: Mapped[str] = mapped_column(String(30), default="unknown")
    customization_max_chars: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    provenance: Mapped[dict] = mapped_column(JSON, default=dict)
    archived: Mapped[bool] = mapped_column(Boolean, default=False)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "store_id", "canonical_url"), CheckConstraint("price_minor >= 0"),
                      ForeignKeyConstraint(["workspace_id", "store_id"], ["stores.workspace_id", "stores.id"]))


class Installation(Tenant, Base):
    __tablename__ = "widget_installations"
    agent_id: Mapped[str] = mapped_column(String(36))
    public_id: Mapped[str] = mapped_column(String(64), unique=True)
    name: Mapped[str] = mapped_column(String(160))
    allowed_origins: Mapped[list] = mapped_column(JSON)
    theme: Mapped[dict] = mapped_column(JSON, default=dict)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (tenant_unique(), ForeignKeyConstraint(["workspace_id", "agent_id"], ["agents.workspace_id", "agents.id"]))


class WebsiteAssistant(Tenant, Base):
    __tablename__ = 'website_assistants'
    kb_id: Mapped[str] = mapped_column(String(36))
    agent_id: Mapped[str] = mapped_column(String(36))
    installation_id: Mapped[str] = mapped_column(String(36))
    options: Mapped[dict] = mapped_column(JSON, default=dict)
    next_crawl_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (tenant_unique(), UniqueConstraint('workspace_id', 'kb_id'),
                     ForeignKeyConstraint(['workspace_id','kb_id'], ['knowledge_bases.workspace_id','knowledge_bases.id']),
                     ForeignKeyConstraint(['workspace_id','agent_id'], ['agents.workspace_id','agents.id']),
                     ForeignKeyConstraint(['workspace_id','installation_id'], ['widget_installations.workspace_id','widget_installations.id']))


class Conversation(Tenant, Base):
    __tablename__ = "conversations"
    installation_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    channel: Mapped[str] = mapped_column(String(20), default="widget")
    state: Mapped[str] = mapped_column(String(20), default="open")
    assigned_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    __table_args__ = (tenant_unique(), ForeignKeyConstraint(["workspace_id", "installation_id"], ["widget_installations.workspace_id", "widget_installations.id"]))


class ConversationContext(Tenant, Base):
    __tablename__ = 'conversation_contexts'
    conversation_id: Mapped[str] = mapped_column(String(36), unique=True)
    variables: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (tenant_unique(), ForeignKeyConstraint(['workspace_id', 'conversation_id'], ['conversations.workspace_id', 'conversations.id']))


class Message(Tenant, Base):
    __tablename__ = "messages"
    conversation_id: Mapped[str] = mapped_column(String(36))
    client_message_id: Mapped[str] = mapped_column(String(36))
    role: Mapped[str] = mapped_column(String(20))
    text_content: Mapped[str] = mapped_column(Text)
    metadata_data: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "conversation_id", "client_message_id", "role"),
                      ForeignKeyConstraint(["workspace_id", "conversation_id"], ["conversations.workspace_id", "conversations.id"]))


class Ticket(Tenant, Base):
    __tablename__ = "tickets"
    conversation_id: Mapped[str] = mapped_column(String(36))
    subject: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text)
    priority: Mapped[str] = mapped_column(String(20), default="normal")
    state: Mapped[str] = mapped_column(String(20), default="open")
    operation_key: Mapped[str] = mapped_column(String(160))
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "operation_key"),
                      ForeignKeyConstraint(["workspace_id", "conversation_id"], ["conversations.workspace_id", "conversations.id"]))


class Lead(Tenant, Base):
    __tablename__ = "leads"
    name: Mapped[str] = mapped_column(String(160))
    email: Mapped[str] = mapped_column(String(254), default="")
    phone: Mapped[str] = mapped_column(String(20), default="")
    stage: Mapped[str] = mapped_column(String(30), default="new")
    evidence: Mapped[str] = mapped_column(Text)
    __table_args__ = (tenant_unique(),)


class Campaign(Tenant, Base):
    __tablename__ = "campaigns"
    name: Mapped[str] = mapped_column(String(160))
    agent_version_id: Mapped[str] = mapped_column(String(36))
    number_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="draft")
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Kolkata")
    concurrency: Mapped[int] = mapped_column(Integer, default=1)
    max_attempts: Mapped[int] = mapped_column(Integer, default=1)
    scheduled_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    contacts: Mapped[list] = mapped_column(JSON, default=list)
    mode: Mapped[str] = mapped_column(String(20), default="simulation")
    budget_minor: Mapped[int] = mapped_column(Integer, default=1000)
    policy: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (tenant_unique(), ForeignKeyConstraint(["workspace_id", "agent_version_id"], ["agent_versions.workspace_id", "agent_versions.id"]),
                      ForeignKeyConstraint(["workspace_id", "number_id"], ["phone_numbers.workspace_id", "phone_numbers.id"]))


class Attempt(Tenant, Base):
    __tablename__ = "campaign_attempts"
    campaign_id: Mapped[str] = mapped_column(String(36))
    contact_identity: Mapped[str] = mapped_column(String(64))
    attempt_index: Mapped[int] = mapped_column(Integer, default=1)
    call_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    state: Mapped[str] = mapped_column(String(20), default="queued")
    outcome: Mapped[str | None] = mapped_column(String(80), nullable=True)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "campaign_id", "contact_identity", "attempt_index"),
                      ForeignKeyConstraint(["workspace_id", "campaign_id"], ["campaigns.workspace_id", "campaigns.id"]),
                      ForeignKeyConstraint(["workspace_id", "call_id"], ["calls.workspace_id", "calls.id"]))


class Connection(Tenant, Base):
    __tablename__ = "connections"
    provider: Mapped[str] = mapped_column(String(60))
    name: Mapped[str] = mapped_column(String(160))
    state: Mapped[str] = mapped_column(String(30), default="disconnected")
    scopes: Mapped[list] = mapped_column(JSON, default=list)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "provider"))


class Appointment(Tenant, Base):
    __tablename__ = "appointments"
    title: Mapped[str] = mapped_column(String(200))
    start_at: Mapped[datetime] = mapped_column(UTCDateTime())
    end_at: Mapped[datetime] = mapped_column(UTCDateTime())
    timezone: Mapped[str] = mapped_column(String(80))
    state: Mapped[str] = mapped_column(String(20), default="local")
    operation_key: Mapped[str] = mapped_column(String(160))
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "operation_key"))


class SchedulingAvailability(Tenant, Base):
    __tablename__ = 'scheduling_availability'
    provider: Mapped[str] = mapped_column(String(20))
    event_type_id: Mapped[str] = mapped_column(String(200))
    context_key: Mapped[str] = mapped_column(String(100), index=True)
    credential_revision: Mapped[str] = mapped_column(String(64))
    timezone: Mapped[str] = mapped_column(String(80))
    event_data: Mapped[dict] = mapped_column(JSON)
    slots: Mapped[list] = mapped_column(JSON)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    __table_args__ = (tenant_unique(),)


class SchedulingBooking(Tenant, Base):
    __tablename__ = 'scheduling_bookings'
    availability_id: Mapped[str] = mapped_column(String(36))
    provider: Mapped[str] = mapped_column(String(20))
    context_key: Mapped[str] = mapped_column(String(100), index=True)
    operation_key: Mapped[str] = mapped_column(String(64))
    prepared_turn: Mapped[str] = mapped_column(String(200))
    confirmation_text: Mapped[str] = mapped_column(Text)
    request_data: Mapped[dict] = mapped_column(JSON)
    state: Mapped[str] = mapped_column(String(24), default='prepared')
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    remote_id: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    remote_event_uri: Mapped[str | None] = mapped_column(String(1000), nullable=True)
    appointment_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (tenant_unique(), UniqueConstraint('workspace_id', 'operation_key'),
                     ForeignKeyConstraint(['workspace_id', 'availability_id'], ['scheduling_availability.workspace_id', 'scheduling_availability.id']),
                     ForeignKeyConstraint(['workspace_id', 'appointment_id'], ['appointments.workspace_id', 'appointments.id']))


class WebhookEndpoint(Tenant, Base):
    __tablename__ = "webhook_endpoints"
    url: Mapped[str] = mapped_column(Text)
    secret: Mapped[str] = mapped_column(Text)
    event_types: Mapped[list] = mapped_column(JSON)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    __table_args__ = (tenant_unique(),)


class Delivery(Tenant, Base):
    __tablename__ = "webhook_deliveries"
    endpoint_id: Mapped[str] = mapped_column(String(36))
    event_id: Mapped[str] = mapped_column(String(36))
    event_type: Mapped[str] = mapped_column(String(80))
    payload: Mapped[dict] = mapped_column(JSON)
    attempt: Mapped[int] = mapped_column(Integer, default=0)
    state: Mapped[str] = mapped_column(String(20), default="pending")
    http_status: Mapped[int | None] = mapped_column(Integer, nullable=True)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(), default=now)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "endpoint_id", "event_id"),
                      ForeignKeyConstraint(["workspace_id", "endpoint_id"], ["webhook_endpoints.workspace_id", "webhook_endpoints.id"]))


class Idempotency(Tenant, Base):
    __tablename__ = "idempotency_records"
    operation_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    result: Mapped[dict] = mapped_column(JSON)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "operation_key"))


class ProviderEvent(Entity, Base):
    __tablename__ = "provider_events"
    provider: Mapped[str] = mapped_column(String(30))
    event_key: Mapped[str] = mapped_column(String(200))
    payload_hash: Mapped[str] = mapped_column(String(64))
    __table_args__ = (UniqueConstraint("provider", "event_key"),)


class Preview(Entity, Base):
    __tablename__ = "website_previews"
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime(), index=True)
    website_url: Mapped[str] = mapped_column(Text)
    data: Mapped[dict] = mapped_column(JSON)
    claimed_workspace_id: Mapped[str | None] = mapped_column(ForeignKey("workspaces.id"), nullable=True)
    claimed_agent_id: Mapped[str | None] = mapped_column(String(36), nullable=True)


class Invitation(Tenant, Base):
    __tablename__ = "team_invitations"
    email: Mapped[str] = mapped_column(String(254), index=True)
    role: Mapped[str] = mapped_column(String(20))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    state: Mapped[str] = mapped_column(String(20), default="pending")
    __table_args__ = (tenant_unique(),)


class AccountToken(Entity, Base):
    __tablename__ = "account_tokens"
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    purpose: Mapped[str] = mapped_column(String(24))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    consumed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)


class Recording(Tenant, Base):
    __tablename__ = "recordings"
    call_id: Mapped[str] = mapped_column(String(36))
    object_key: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[int] = mapped_column(Integer)
    size_bytes: Mapped[int] = mapped_column(Integer)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime())
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    __table_args__ = (tenant_unique(), UniqueConstraint("workspace_id", "call_id"),
                      ForeignKeyConstraint(["workspace_id", "call_id"], ["calls.workspace_id", "calls.id"]))


class ConnectorCredential(Tenant, Base):
    __tablename__ = 'connector_credentials'
    provider: Mapped[str] = mapped_column(String(60))
    encrypted_data: Mapped[str] = mapped_column(Text)
    __table_args__ = (tenant_unique(), UniqueConstraint('workspace_id','provider'))


class ConnectorAction(Tenant, Base):
    __tablename__ = 'connector_actions'
    provider: Mapped[str] = mapped_column(String(60))
    action: Mapped[str] = mapped_column(String(60))
    operation_key: Mapped[str] = mapped_column(String(200))
    request_hash: Mapped[str] = mapped_column(String(64))
    state: Mapped[str] = mapped_column(String(24), default='pending')
    result: Mapped[dict] = mapped_column(JSON, default=dict)
    __table_args__ = (tenant_unique(),UniqueConstraint('workspace_id','operation_key'))


class PaymentOrder(Tenant, Base):
    __tablename__ = 'payment_orders'
    amount_minor: Mapped[int] = mapped_column(Integer)
    net_minor: Mapped[int | None] = mapped_column(Integer,nullable=True)
    quote_hash: Mapped[str | None] = mapped_column(String(64),nullable=True)
    encrypted_snapshot: Mapped[str | None] = mapped_column(Text,nullable=True)
    captured_at: Mapped[datetime | None] = mapped_column(UTCDateTime(),nullable=True)
    reversed_net_minor: Mapped[int] = mapped_column(Integer,default=0)
    refunded_net_minor: Mapped[int] = mapped_column(Integer,default=0)
    refunded_gross_minor: Mapped[int] = mapped_column(Integer,default=0)
    currency: Mapped[str] = mapped_column(String(3),default='INR')
    provider_order_id: Mapped[str | None] = mapped_column(String(100),nullable=True,unique=True)
    provider_payment_id: Mapped[str | None] = mapped_column(String(100),nullable=True,unique=True)
    operation_key: Mapped[str] = mapped_column(String(200))
    state: Mapped[str] = mapped_column(String(24),default='creating')
    __table_args__ = (tenant_unique(),UniqueConstraint('workspace_id','operation_key'),CheckConstraint('amount_minor > 0'))


class BillingWebhookInbox(Entity,Base):
    __tablename__='billing_webhook_inbox'
    provider_event_id: Mapped[str] = mapped_column(String(200),unique=True)
    payload_hash: Mapped[str] = mapped_column(String(64))
    encrypted_payload: Mapped[str | None] = mapped_column(Text,nullable=True)
    state: Mapped[str] = mapped_column(String(20),default='pending',index=True)
    attempts: Mapped[int] = mapped_column(Integer,default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(UTCDateTime(),default=now,index=True)
    lease_token: Mapped[str | None] = mapped_column(String(36),nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(40),nullable=True)


class BillingFinancialEvent(Tenant,Base):
    __tablename__='billing_financial_events'
    operation_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(60))
    provider_id: Mapped[str | None] = mapped_column(String(100),nullable=True)
    details: Mapped[dict] = mapped_column(JSON)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','operation_key'))


class BillingAccount(Tenant,Base):
    __tablename__='billing_accounts'
    debt_minor: Mapped[int] = mapped_column(BigInteger,default=0)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id'),CheckConstraint('debt_minor >= 0'))


class PaymentRefund(Tenant,Base):
    __tablename__='payment_refunds'
    order_id: Mapped[str] = mapped_column(String(36))
    operation_key: Mapped[str] = mapped_column(String(200))
    provider_refund_id: Mapped[str | None] = mapped_column(String(100),nullable=True,unique=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    reserved_net_minor: Mapped[int] = mapped_column(Integer,default=0)
    state: Mapped[str] = mapped_column(String(24),default='creating')
    last_event_at: Mapped[int] = mapped_column(BigInteger,default=0)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','operation_key'),
        ForeignKeyConstraint(['workspace_id','order_id'],['payment_orders.workspace_id','payment_orders.id']),
        CheckConstraint('amount_minor > 0'))


class PaymentDispute(Tenant,Base):
    __tablename__='payment_disputes'
    order_id: Mapped[str] = mapped_column(String(36))
    provider_dispute_id: Mapped[str] = mapped_column(String(100),unique=True)
    amount_minor: Mapped[int] = mapped_column(Integer)
    risk_net_minor: Mapped[int] = mapped_column(Integer,default=0)
    deducted_net_minor: Mapped[int] = mapped_column(Integer,default=0)
    state: Mapped[str] = mapped_column(String(24),default='open')
    last_event_at: Mapped[int] = mapped_column(BigInteger,default=0)
    __table_args__=(tenant_unique(),ForeignKeyConstraint(['workspace_id','order_id'],['payment_orders.workspace_id','payment_orders.id']),
        CheckConstraint('amount_minor > 0'))


class BillingProviderOperation(Tenant,Base):
    __tablename__='billing_provider_operations'
    operation_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(30))
    request_hash: Mapped[str] = mapped_column(String(64))
    provider_id: Mapped[str | None] = mapped_column(String(100),nullable=True)
    state: Mapped[str] = mapped_column(String(24),default='creating')
    details: Mapped[dict] = mapped_column(JSON)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','operation_key'),UniqueConstraint('kind','provider_id'))


class InvoiceSequence(Entity,Base):
    __tablename__='invoice_sequences'
    entity_id: Mapped[str] = mapped_column(String(40))
    financial_year: Mapped[str] = mapped_column(String(4))
    last_number: Mapped[int] = mapped_column(Integer,default=0)
    __table_args__=(UniqueConstraint('entity_id','financial_year'),)


class Invoice(Tenant,Base):
    __tablename__='billing_invoices'
    operation_key: Mapped[str] = mapped_column(String(200))
    kind: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[str] = mapped_column(String(40))
    number: Mapped[str] = mapped_column(String(16))
    snapshot: Mapped[dict] = mapped_column(JSON)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','operation_key'),UniqueConstraint('entity_id','number'))


class InvoiceDelivery(Tenant,Base):
    __tablename__='invoice_deliveries'
    invoice_id: Mapped[str] = mapped_column(String(36))
    object_key: Mapped[str | None] = mapped_column(String(200),nullable=True)
    state: Mapped[str] = mapped_column(String(20),default='pending')
    emailed_at: Mapped[datetime | None] = mapped_column(UTCDateTime(),nullable=True)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','invoice_id'),
        ForeignKeyConstraint(['workspace_id','invoice_id'],['billing_invoices.workspace_id','billing_invoices.id']))


class LLMProfile(Tenant, Base):
    __tablename__='llm_profiles'
    name: Mapped[str]=mapped_column(String(160))
    model: Mapped[str]=mapped_column(String(200))
    base_url: Mapped[str]=mapped_column(Text)
    encrypted_key: Mapped[str]=mapped_column(Text)
    api_style: Mapped[str]=mapped_column(String(24),default='chat_completions')
    token_parameter: Mapped[str]=mapped_column(String(40),default='max_completion_tokens')
    options: Mapped[dict]=mapped_column(JSON,default=dict)
    research: Mapped[dict]=mapped_column(JSON,default=dict)
    enabled: Mapped[bool]=mapped_column(Boolean,default=True)
    __table_args__=(tenant_unique(),)


class HTTPTool(Tenant, Base):
    __tablename__='http_tools'
    name: Mapped[str]=mapped_column(String(64))
    description: Mapped[str]=mapped_column(Text)
    revision: Mapped[int]=mapped_column(Integer,default=1)
    config: Mapped[dict]=mapped_column(JSON)
    encrypted_headers: Mapped[str]=mapped_column(Text)
    enabled: Mapped[bool]=mapped_column(Boolean,default=True)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','name'))


class ToolExecution(Tenant, Base):
    __tablename__='tool_executions'
    tool_id: Mapped[str]=mapped_column(String(36))
    operation_key: Mapped[str]=mapped_column(String(200))
    request_hash: Mapped[str]=mapped_column(String(64))
    call_id: Mapped[str | None]=mapped_column(String(36),nullable=True)
    state: Mapped[str]=mapped_column(String(24),default='queued')
    payload: Mapped[dict]=mapped_column(JSON)
    result: Mapped[dict]=mapped_column(JSON,default=dict)
    elapsed_ms: Mapped[int | None]=mapped_column(Integer,nullable=True)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','operation_key'),ForeignKeyConstraint(['workspace_id','tool_id'],['http_tools.workspace_id','http_tools.id']))


class HTTPToolVersion(Tenant, Base):
    __tablename__='http_tool_versions'
    tool_id: Mapped[str]=mapped_column(String(36))
    revision: Mapped[int]=mapped_column(Integer)
    name: Mapped[str]=mapped_column(String(64))
    description: Mapped[str]=mapped_column(Text)
    config: Mapped[dict]=mapped_column(JSON)
    encrypted_headers: Mapped[str]=mapped_column(Text)
    __table_args__=(tenant_unique(),UniqueConstraint('workspace_id','tool_id','revision'),ForeignKeyConstraint(['workspace_id','tool_id'],['http_tools.workspace_id','http_tools.id']))


class TransferPolicy(Tenant, Base):
    __tablename__ = 'transfer_policies'
    revision: Mapped[str] = mapped_column(String(36))
    label: Mapped[str] = mapped_column(String(100))
    encrypted_destination: Mapped[str] = mapped_column(Text)
    maximum_seconds: Mapped[int] = mapped_column(Integer, default=120)
    enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    approved_by: Mapped[str | None] = mapped_column(String(36), nullable=True)
    __table_args__ = (tenant_unique(), UniqueConstraint('workspace_id'),)


class CallTransfer(Tenant, Base):
    __tablename__ = 'call_transfers'
    call_id: Mapped[str] = mapped_column(String(36), unique=True)
    consent_id: Mapped[str] = mapped_column(String(36), unique=True)
    provider: Mapped[str] = mapped_column(String(20))
    parent_leg_id: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(24), default='queued', index=True)
    encrypted_snapshot: Mapped[str] = mapped_column(Text)
    maximum_seconds: Mapped[int] = mapped_column(Integer)
    deadline_at: Mapped[datetime] = mapped_column(UTCDateTime())
    submitted_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    xml_served_at: Mapped[datetime | None] = mapped_column(UTCDateTime(), nullable=True)
    child_leg_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    child_bill_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    child_outcome: Mapped[str | None] = mapped_column(String(40), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    __table_args__ = (tenant_unique(), ForeignKeyConstraint(['workspace_id','call_id'],['calls.workspace_id','calls.id']),)
