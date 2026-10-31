from datetime import datetime
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict, field_validator, AwareDatetime
import re


class Input(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class Signup(Input):
    legal_accepted: bool = Field(default=False, strict=True)
    legal_version: str = Field(default="", max_length=80)
    email: str = Field(max_length=254)
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=12, max_length=256)
    workspace_name: str = Field(min_length=1, max_length=120)

    @field_validator("email")
    @classmethod
    def email_valid(cls, value):
        if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError("Enter a valid email address")
        return value.lower()


class Signin(Input):
    email: str = Field(max_length=254)
    password: str = Field(max_length=256)


class WorkspaceWrite(Input):
    name: str = Field(min_length=1, max_length=120)
    timezone: str = "Asia/Kolkata"
    currency: str = Field(default="INR", pattern="^[A-Z]{3}$")


class KBCreate(Input):
    name: str = Field(min_length=1, max_length=160)
    website_url: str = Field(min_length=8, max_length=2000)
    max_pages: int = Field(default=15, ge=1, le=100)


class KBUpdate(Input):
    name: str | None = Field(default=None, max_length=160)
    priority_guidance: str | None = Field(default=None, max_length=12000)


class Query(Input):
    query: str = Field(min_length=1, max_length=4000)
    limit: int = Field(default=6, ge=1, le=20)


class AgentCreate(Input):
    name: str = Field(min_length=1, max_length=160)
    config: dict | None = None
    website_url: str | None = Field(default=None, max_length=2000)


class AgentDraft(Input):
    expected_revision: int = Field(ge=1)
    config: dict


class Publish(Input):
    expected_draft_revision: int = Field(ge=1)


class Brief(Input):
    goal: str = Field(min_length=3, max_length=10000)
    language: str = "en"
    business_url: str = ""


class BrowserSession(Input):
    agent_id: str
    mode: Literal["simulation", "live"] = "simulation"
    variables: dict[str,str] = Field(default_factory=dict)


class Outbound(Input):
    agent_id: str
    number_id: str | None = None
    destination: str = Field(pattern=r"^\+[1-9][0-9]{6,14}$")
    budget_minor: int = Field(default=500, ge=1, le=100000)
    mode: Literal["simulation", "live"] = "simulation"
    variables: dict[str,str] = Field(default_factory=dict)


class StoreWrite(Input):
    name: str = Field(min_length=1, max_length=160)
    website_url: str = Field(min_length=8, max_length=2000)


class ProductWrite(Input):
    store_id: str
    title: str = Field(min_length=1, max_length=300)
    canonical_url: str = Field(min_length=8, max_length=2000)
    description: str = Field(default="", max_length=20000)
    price_minor: int = Field(ge=0)
    currency: str = Field(default="INR", pattern="^[A-Z]{3}$")
    availability: Literal["in_stock", "out_of_stock", "unknown"] = "unknown"
    customization_max_chars: int | None = Field(default=None, ge=0, le=10000)


class InstallationWrite(Input):
    agent_id: str
    name: str = Field(min_length=1, max_length=160)
    allowed_origins: list[str] = Field(min_length=1, max_length=20)
    theme: dict = Field(default_factory=dict)
    enabled: bool = True

    @field_validator('theme')
    @classmethod
    def theme_valid(cls, value):
        from .widget_branding import validate_theme
        return validate_theme(value)


class PublicSession(Input):
    installation_public_id: str
    public_key: str | None = Field(default=None, max_length=200)
    variables: dict[str, str] = Field(default_factory=dict, max_length=30)
    visitor_email: str | None = Field(default=None, max_length=254)
    marketing_opt_in: bool = False
    bot_token: str | None = Field(default=None,max_length=2048)

    @field_validator('visitor_email')
    @classmethod
    def visitor_email_valid(cls, value):
        if value is not None and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", value):
            raise ValueError('Enter a valid email address')
        return value.lower() if value else value


class ChatRequest(Input):
    session_id: str
    message: str = Field(min_length=1, max_length=8000)
    client_message_id: str = Field(min_length=1, max_length=36)
    page_url: str | None = Field(default=None, max_length=2000)
    confirmation_id: str | None = Field(default=None, max_length=36)


class PublicVoiceSession(Input):
    installation_public_id: str
    page_url: str | None = Field(default=None, max_length=2000)


class TicketCreate(Input):
    conversation_id: str
    subject: str = Field(min_length=1, max_length=200)
    description: str = Field(min_length=1, max_length=12000)
    priority: Literal["low", "normal", "high"] = "normal"


class LeadWrite(Input):
    name: str = Field(min_length=1, max_length=160)
    email: str = Field(default="", max_length=254)
    phone: str = Field(default="", max_length=20)
    stage: Literal["new", "qualified", "contacted", "won", "lost"] = "new"
    evidence: str = Field(min_length=1, max_length=6000)


class CampaignWrite(Input):
    name: str = Field(min_length=1, max_length=160)
    agent_version_id: str
    number_id: str | None = None
    timezone: str = "Asia/Kolkata"
    concurrency: int = Field(default=1, ge=1, le=8)
    max_attempts: int = Field(default=1, ge=1, le=5)
    scheduled_at: datetime | None = None
    budget_minor: int = Field(default=1000, ge=1)
    mode: Literal["simulation", "live"] = "simulation"
    retry_delay_seconds: int = Field(default=300,ge=30,le=86400)
    calling_hour_start: int = Field(default=9,ge=0,le=23)
    calling_hour_end: int = Field(default=21,ge=1,le=24)


class ContactsImport(Input):
    contacts: list[dict] = Field(max_length=10000)
    dry_run: bool = True


class NumberWrite(Input):
    e164: str = Field(pattern=r"^\+[1-9][0-9]{6,14}$")
    provider: Literal["plivo","twilio"] = "plivo"
    can_inbound: bool = False
    can_outbound: bool = True


class RouteWrite(Input):
    agent_id: str


class KeyWrite(Input):
    name: str = Field(min_length=1, max_length=120)
    scopes: list[str] = Field(min_length=1, max_length=40)
    expires_at: AwareDatetime | None = None
    requests_per_minute: int = Field(default=60, ge=1, le=600)


class WebhookWrite(Input):
    url: str = Field(min_length=8, max_length=2000)
    events: list[str] = Field(min_length=1, max_length=20)
    enabled: bool = True


class AppointmentWrite(Input):
    title: str = Field(min_length=1, max_length=200)
    start: datetime
    end: datetime
    timezone: str = "Asia/Kolkata"


class SettingsWrite(Input):
    business_name: str = Field(min_length=1, max_length=160)
    industry: str = Field(default="", max_length=100)
    timezone: str
    notifications_enabled: bool = True
