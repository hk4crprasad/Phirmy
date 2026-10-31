from pathlib import Path
import os
import secrets
from typing import Literal
from pydantic import Field,AliasChoices
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    plans_config_path: str = str(Path(__file__).resolve().parents[3]/'config/plans.json')
    paid_activation_enabled: bool = False
    razorpay_webhook_previous_secrets_json: str = ''
    billing_business_config_path: str = str(Path(__file__).resolve().parents[3] / 'config' / 'billing_business.json')
    billing_development_allowances_enabled: bool = False
    billing_max_llm_input_bytes: int = 65536
    billing_max_llm_output_tokens: int = 1200
    cipher_key_provider: Literal['local','azure-key-vault'] = 'local'
    cipher_active_key_id: str = 'app-v1'
    cipher_keys_json: str = ''
    cipher_vault_url: str = ''
    cipher_vault_secret_name: str = 'studio-cipher-key'
    cipher_rotation_operator_emails: str = ''
    legal_config_path: str = str(Path(__file__).resolve().parents[3] / 'config' / 'legal.json')
    billing_operator_emails: str = ''
    billing_operator_refunds_enabled: bool = False
    turnstile_site_key: str = ''
    turnstile_secret_key: str = ''
    widget_bot_challenge_enabled: bool = False
    widget_marketing_consent_enabled: bool = False
    widget_daily_sessions: int = Field(default=1000,ge=1,le=100000)
    widget_daily_turns: int = Field(default=5000,ge=1,le=100000)
    widget_ip_daily_sessions: int = Field(default=100,ge=1,le=10000)
    widget_ip_daily_turns: int = Field(default=1000,ge=1,le=10000)
    widget_monthly_spend_cap_minor: int = Field(default=100000,ge=0)
    widget_chat_reservation_minor: int = Field(default=100,ge=1)
    widget_voice_reservation_minor: int = Field(default=1000,ge=1)
    widget_transcription_reservation_minor: int = Field(default=100,ge=1)
    widget_voice_max_seconds: int = Field(default=300,ge=10,le=300)
    content_sandbox_socket: str = '/run/studio-sandbox/content.sock'
    content_sandbox_timeout_seconds: int = Field(default=45,ge=1,le=120)
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    app_env: str = "development"
    app_origin: str = "http://localhost:3100"
    public_api_origin: str = "http://localhost:8100"
    database_url: str = "sqlite:///./data/studio.db"
    supabase_db_host: str = ""
    supabase_db_user: str = "postgres"
    supabase_db_password: str = ""
    supabase_db_name: str = "postgres"
    object_storage_provider: str = "local"
    azure_storage_connection_string: str = ""
    azure_storage_account_url: str = ""
    azure_storage_container: str = "voice-studio"
    azure_storage_prefix: str = ""
    embedding_provider: str = "openai-compatible"
    embedding_base_url: str = ""
    embedding_api_key: str = ""
    embedding_model: str = "text-embedding-3-small"
    embedding_dimensions: int | None = 1536
    vector_provider: str = "qdrant"
    vector_endpoint: str = ""
    vector_api_key: str = ""
    vector_collection: str = "voice-studio"
    app_secret: str = ""
    session_secure: bool = False
    openai_api_key: str = ""
    openai_model: str = Field(default="gpt-5.6-luna",validation_alias=AliasChoices('OPENAI_MODEL','OPENAI_CHAT_MODEL','openai_model'))
    openai_base_url: str = 'https://api.openai.com/v1'
    openai_api_style: str = 'auto'
    openai_token_parameter: str = 'auto'
    openai_reasoning_effort: str = 'auto'
    fish_api_key: str = ""
    fish_voice_id: str = ""
    fish_tts_model: str = "s2.1-pro"
    voice_tts_reservation_bytes: int = Field(default=512,ge=32,le=4096)
    voice_prompt_cache_enabled: bool = True
    voice_llm_keepalive_enabled: bool = True
    voice_fish_preconnect_enabled: bool = True
    voice_greeting_cache_enabled: bool = True
    voice_prefetch_enabled: bool = True
    voice_prefetch_debounce_ms: int = Field(default=250,ge=10,le=1000)
    voice_prefetch_max_requests: int = Field(default=2,ge=1,le=2)
    voice_prefetch_result_ttl_seconds: int = Field(default=5,ge=0,le=30)
    deepgram_api_key: str = ""
    deepgram_language: str = "en"
    voice_provider: Literal['sarvam', 'legacy'] = 'sarvam'
    sarvam_api_key: str = ''
    sarvam_stt_model: Literal['saaras:v4'] = 'saaras:v4'
    sarvam_tts_model: Literal['bulbul:v4-flash'] = 'bulbul:v4-flash'
    sarvam_voice_model: Literal['sarvam-105b-conversations'] = 'sarvam-105b-conversations'
    sarvam_voice_id: str = 'simran_enhi_customer'
    sarvam_language: str = 'auto'
    sarvam_endpointing_ms: int = Field(default=250, ge=100, le=1500)
    plivo_auth_id: str = ""
    plivo_auth_token: str = ""
    plivo_caller_id: str = ""
    twilio_account_sid: str = ''
    twilio_auth_token: str = ''
    twilio_api_key: str = ''
    twilio_api_secret: str = ''
    twilio_caller_id: str = ''
    media_public_origin: str = ""
    live_calls_enabled: bool = False
    phone_trials_enabled: bool = False
    phone_trial_auto_assign_pool_id: str = ''
    phone_number_purchases_enabled: bool = False
    phone_number_max_monthly_price_minor: int = Field(default=150, ge=1, le=10000)
    phone_number_total_budget_minor: int = Field(default=1500, ge=1, le=100000)
    beta_operator_email: str = ''
    test_destination_allowlist: str = ""
    razorpay_key_id: str = ""
    razorpay_key_secret: str = ""
    razorpay_mode: Literal['test','live'] = 'test'
    razorpay_test_key_id: str = ''
    razorpay_test_key_secret: str = ''
    razorpay_live_key_id: str = ''
    razorpay_live_key_secret: str = ''
    razorpay_webhook_secret: str = ""
    live_payments_enabled: bool = False
    dev_seed_enabled: bool = True
    contact_site_origin: str = "https://phirmy.com"
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    smtp_from: str = "Phirmy <noreply@localhost>"
    smtp_security: Literal['starttls', 'ssl'] = 'starttls'
    google_client_id: str = ''
    google_client_secret: str = ''
    calcom_client_id: str = ''
    calcom_client_secret: str = ''
    calcom_oauth_mode: Literal['confidential', 'public'] = 'confidential'
    calendly_client_id: str = ''
    calendly_client_secret: str = ''
    require_email_verification: bool = True
    access_token_seconds: int = 900
    session_days: int = 7
    max_account_sessions: int = 10
    max_owned_workspaces: int = Field(default=5, ge=1, le=100)
    auth_response_floor_ms: int = Field(default=500, ge=250, le=5000)
    email_max_attempts: int = Field(default=8, ge=1, le=30)
    callback_requests_enabled: bool = True
    live_transfer_enabled: bool = False
    tool_calls_per_conversation: int = Field(default=8, ge=1, le=64)
    tool_confirmation_seconds: int = Field(default=300, ge=30, le=600)
    workspace_daily_turn_limit: int = 2000
    workspace_voice_concurrency: int = 2
    public_network_mode: Literal["direct", "proxy"] = "direct"
    public_http_proxy: str = ""
    redis_url: str = ""
    widget_frame_cache_namespace: str = Field(default='studio:widget-frame:v1', pattern=r'^[A-Za-z0-9:_-]{1,120}$')
    trusted_proxy_ips: str = ""
    embedding_cache_seconds: int = Field(default=604800, ge=1, le=2592000)
    crawl_concurrency: int = Field(default=4, ge=1, le=8)
    render_concurrency: int = Field(default=2, ge=1, le=4)
    index_concurrency: int = Field(default=2, ge=1, le=8)
    worker_enabled: bool = True
    worker_concurrency: int = Field(default=4, ge=1, le=16)
    worker_poll_seconds: float = Field(default=.25, ge=.05, le=5)
    worker_group: str = Field(default='default', min_length=1, max_length=80)
    request_max_bytes: int = Field(default=21_000_000, ge=1024, le=100_000_000)
    request_json_max_bytes: int = Field(default=1_000_000, ge=1024, le=10_000_000)
    request_body_timeout_seconds: int = Field(default=30, ge=1, le=120)
    database_pool_size: int = Field(default=5, ge=1, le=50)
    database_max_overflow: int = Field(default=5, ge=0, le=50)
    data_dir: str = "data"

    def initialize(self):
        import ipaddress
        for proxy in filter(None, (value.strip() for value in self.trusted_proxy_ips.split(','))):
            network = ipaddress.ip_network(proxy, strict=False)
            if network.prefixlen == 0:
                raise RuntimeError('TRUSTED_PROXY_IPS must identify specific proxy IPs or networks')
        if self.supabase_db_password:
            if not self.supabase_db_host:
                raise RuntimeError('SUPABASE_DB_HOST is required when using split database credentials')
            from urllib.parse import quote
            self.database_url = (
                "postgresql+psycopg://" + quote(self.supabase_db_user, safe="") + ":"
                + quote(self.supabase_db_password, safe="") + "@" + self.supabase_db_host
                + ":5432/" + quote(self.supabase_db_name, safe="") + "?sslmode=require"
            )
        elif self.database_url.startswith("postgresql://"):
            self.database_url = self.database_url.replace("postgresql://", "postgresql+psycopg://", 1)
        Path(self.data_dir).mkdir(parents=True, exist_ok=True)
        if self.app_env == "production":
            if len(self.app_secret) < 32 or not self.session_secure:
                raise RuntimeError("Production requires APP_SECRET >=32 characters and SESSION_SECURE=true")
            if self.database_url.startswith("sqlite"):
                raise RuntimeError("SQLite is a local development mode; configure PostgreSQL for production")
            if self.dev_seed_enabled:
                raise RuntimeError("Disable DEV_SEED_ENABLED in production")
            if self.object_storage_provider != "azure":
                raise RuntimeError("Production requires Azure Blob Storage")
        if not self.app_secret:
            path = Path(self.data_dir) / ".session-secret"
            try:
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as file:
                    file.write(secrets.token_urlsafe(48))
            except FileExistsError:
                pass
            self.app_secret = path.read_text().strip()
        if self.openai_api_style not in {'auto','responses','chat_completions'}:
            raise RuntimeError('OPENAI_API_STYLE must be auto, responses or chat_completions')

    def razorpay_credentials(self):
        key_id=getattr(self,'razorpay_'+self.razorpay_mode+'_key_id')
        key_secret=getattr(self,'razorpay_'+self.razorpay_mode+'_key_secret')
        if key_id or key_secret:
            return key_id,key_secret
        # Backward compatibility cannot select a recognizable key from the other mode.
        if self.razorpay_key_id.startswith('rzp_') and not self.razorpay_key_id.startswith('rzp_'+self.razorpay_mode+'_'):
            return '',''
        return self.razorpay_key_id,self.razorpay_key_secret

    def capabilities(self):
        payment_key,payment_secret=self.razorpay_credentials()
        sarvam = self.voice_provider == 'sarvam'
        return {
            "llm": bool(self.openai_api_key),
            "tts": bool(self.sarvam_api_key and self.sarvam_voice_id) if sarvam else bool(self.fish_api_key and self.fish_voice_id),
            "stt": bool(self.sarvam_api_key) if sarvam else bool(self.deepgram_api_key),
            "live_voice": bool(self.sarvam_api_key and self.sarvam_voice_id) if sarvam else bool(self.openai_api_key and self.fish_api_key and self.fish_voice_id and self.deepgram_api_key),
            "voice_provider": self.voice_provider,
            "voice_model": self.sarvam_voice_model if sarvam else self.openai_model,
            "voice_id": self.sarvam_voice_id if sarvam else self.fish_voice_id,
            "stt_model": self.sarvam_stt_model if sarvam else 'nova-3',
            "telephony": bool(self.live_calls_enabled and self.media_public_origin and ((self.plivo_auth_id and self.plivo_auth_token and self.plivo_caller_id) or (self.twilio_account_sid and self.twilio_auth_token and self.twilio_caller_id))),
            'telephony_providers':(["plivo"] if self.plivo_auth_id and self.plivo_auth_token else [])+(["twilio"] if self.twilio_account_sid and self.twilio_auth_token else []),
            'public_webhook_origin':self.media_public_origin or self.public_api_origin,
            "payments": bool(self.live_payments_enabled and payment_key and payment_secret and self.razorpay_webhook_secret),
            'payment_mode':self.razorpay_mode,
            "model": self.openai_model,
            "tts_model": self.sarvam_tts_model if sarvam else self.fish_tts_model,
            "retrieval": "qdrant-hybrid" if self.vector_endpoint and (self.embedding_api_key or self.openai_api_key) else "lexical-development",
            "database": "sqlite-development" if self.database_url.startswith("sqlite") else "postgresql",
            "object_storage": self.object_storage_provider,
            "embedding_model": self.embedding_model or None,
            "vector_provider": self.vector_provider or None,
        }


settings = Settings()
settings.initialize()
