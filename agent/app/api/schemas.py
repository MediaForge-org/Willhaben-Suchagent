from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from agent.app.core.models import EnrichmentStatus, SearchCategory, SellerType


class SearchPayloadBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    category: SearchCategory
    enabled: bool = True
    query: str = Field(default="", max_length=500)
    location: str | None = Field(default=None, max_length=300)
    price_min: Decimal | None = Field(default=None, ge=0)
    price_max: Decimal | None = Field(default=None, ge=0)
    category_filters: dict[str, Any] = Field(default_factory=dict)
    default_template_id: int | None = Field(default=None, ge=1)
    notification_target_ids: list[int] = Field(default_factory=list)
    notify_desktop_sound: bool = True

    @model_validator(mode="after")
    def validate_price_range(self):
        if self.price_min is not None and self.price_max is not None:
            if self.price_min > self.price_max:
                raise ValueError("price_min must not exceed price_max")
        return self


class SearchCreate(SearchPayloadBase):
    model_config = ConfigDict(extra="forbid")


class SearchPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    category: SearchCategory | None = None
    enabled: bool | None = None
    query: str | None = Field(default=None, max_length=500)
    location: str | None = Field(default=None, max_length=300)
    price_min: Decimal | None = Field(default=None, ge=0)
    price_max: Decimal | None = Field(default=None, ge=0)
    category_filters: dict[str, Any] | None = None
    default_template_id: int | None = Field(default=None, ge=1)
    notification_target_ids: list[int] | None = None
    notify_desktop_sound: bool | None = None


class SearchResponse(SearchPayloadBase):
    id: int
    baseline_initialized: bool
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None
    last_success_at: datetime | None
    consecutive_errors: int


class HealthResponse(BaseModel):
    status: str
    process_started_at: datetime
    last_cycle_started_at: datetime | None
    next_cycle_due_at: datetime | None
    last_cycle_completed_at: datetime | None
    last_successful_cycle_at: datetime | None
    last_successful_willhaben_cycle_at: datetime | None
    active_searches: int
    total_cycle_count: int
    failed_cycle_count: int


class StatusResponse(HealthResponse):
    app_version: str
    environment: str
    scheduler_running: bool
    cycle_interval_seconds: float
    max_concurrent_requests: int
    last_cycle_duration_seconds: float | None
    last_cycle_error: str | None
    last_notification_error: str | None
    last_provider_errors: dict[int, str]
    pending_notifications: int
    failed_notifications: int
    last_successful_notification_at: datetime | None
    notifications_enabled: bool
    notifications_disabled_reason: str | None
    desktop_sound_enabled: bool
    desktop_sound_id: str
    desktop_sound_available: bool
    desktop_sound_disabled_reason: str | None
    database_counts: dict[str, int]


class RecentListingResponse(BaseModel):
    listing_id: int
    provider_listing_id: str
    title: str
    article_label: str
    article_phrase: str
    price: Decimal | None
    location: str | None
    image_url: str | None
    seller_name: str | None
    seller_type: SellerType | None
    condition: str | None
    enrichment_status: EnrichmentStatus
    url: str
    first_seen_at: datetime
    search_ids: list[int]
    search_names: list[str]


class NotificationTestResponse(BaseModel):
    status: str
    message: str


class DesktopSoundTestResponse(BaseModel):
    status: str
    message: str


class DesktopSoundOption(BaseModel):
    id: str
    name: str


class GlobalNotificationSettingsResponse(BaseModel):
    """Shared, provider-technical settings only — per-destination config lives in
    notification targets (see NotificationTargetResponse)."""

    ntfy_timeout_seconds: float
    discord_timeout_seconds: float
    email_smtp_host: str | None
    email_smtp_port: int
    email_smtp_username: str | None
    email_smtp_password_configured: bool
    email_from_address: str | None
    email_encryption: Literal["starttls", "ssl", "none"]
    email_timeout_seconds: float


class GlobalNotificationSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ntfy_timeout_seconds: float | None = Field(default=None, gt=0, le=120)
    discord_timeout_seconds: float | None = Field(default=None, gt=0, le=120)
    email_smtp_host: str | None = Field(default=None, max_length=300)
    email_smtp_port: int | None = Field(default=None, ge=1, le=65535)
    email_smtp_username: str | None = Field(default=None, max_length=300)
    email_smtp_password: str | None = Field(default=None, max_length=500)
    email_from_address: str | None = Field(default=None, max_length=300)
    email_encryption: Literal["starttls", "ssl", "none"] | None = None
    email_timeout_seconds: float | None = Field(default=None, gt=0, le=120)


class AgentSettingsResponse(BaseModel):
    desktop_sound_enabled: bool
    desktop_sound_id: str
    desktop_sounds: list[DesktopSoundOption]
    notifications: GlobalNotificationSettingsResponse | None = None


class ChannelTestResponse(BaseModel):
    status: str
    message: str


class NotificationTargetResponse(BaseModel):
    id: int
    type: Literal["ntfy", "discord", "email"]
    name: str
    enabled: bool
    configured: bool
    ntfy_base_url: str | None
    ntfy_topic_configured: bool
    ntfy_token_configured: bool
    discord_webhook_configured: bool
    email_address: str | None
    email_address_masked: str | None
    usage_count: int = 0
    created_at: str
    updated_at: str


class NotificationTargetCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["ntfy", "discord", "email"]
    name: str = Field(min_length=1, max_length=200)
    enabled: bool = True
    base_url: str | None = Field(default=None, max_length=500)
    topic: str | None = Field(default=None, max_length=200)
    token: str | None = Field(default=None, max_length=500)
    webhook_url: str | None = Field(default=None, max_length=500)
    email_address: str | None = Field(default=None, max_length=300)


class NotificationTargetPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    enabled: bool | None = None
    base_url: str | None = Field(default=None, max_length=500)
    topic: str | None = Field(default=None, max_length=200)
    token: str | None = Field(default=None, max_length=500)
    webhook_url: str | None = Field(default=None, max_length=500)
    email_address: str | None = Field(default=None, max_length=300)


class NotificationTargetDeleteResponse(BaseModel):
    deleted: bool
    searches_affected: int


class AgentSettingsPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    desktop_sound_enabled: bool | None = None
    desktop_sound_id: str | None = Field(default=None, min_length=1, max_length=50)


class DesktopSoundTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    desktop_sound_id: str | None = Field(default=None, min_length=1, max_length=50)


class TemplateBase(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=10_000)


class TemplateCreate(TemplateBase):
    model_config = ConfigDict(extra="forbid")


class TemplatePatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = Field(default=None, min_length=1, max_length=10_000)


class TemplateResponse(TemplateBase):
    id: int
    created_at: datetime
    updated_at: datetime


class TemplateRenderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    listing_id: int = Field(ge=1)


class TemplateRenderResponse(BaseModel):
    template_id: int
    listing_id: int
    rendered_text: str


class MarketplaceOption(BaseModel):
    label: str
    value: str


class MarketplaceOptionsResponse(BaseModel):
    categories: list[MarketplaceOption]
    locations: list[MarketplaceOption]


class ImportSearchUrlRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    url: str = Field(min_length=1, max_length=2000)


class ImportedSearchDraftResponse(BaseModel):
    category_path: str | None
    category_label: str | None
    query: str
    location: str | None
    price_min: Decimal | None
    price_max: Decimal | None
    unsupported_filters: list[str]


class BackupImportSummaryResponse(BaseModel):
    templates_created: int
    templates_skipped: int
    notification_targets_created: int
    notification_targets_skipped: int
    searches_created: int
    searches_skipped: int
