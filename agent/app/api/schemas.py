from datetime import datetime
from decimal import Decimal
from typing import Any

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
    notify_ntfy: bool = True
    notify_discord: bool = True
    notify_email: bool = True
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
    notify_ntfy: bool | None = None
    notify_discord: bool | None = None
    notify_email: bool | None = None
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
    ntfy_enabled: bool
    ntfy_disabled_reason: str | None
    discord_enabled: bool
    discord_disabled_reason: str | None
    email_enabled: bool
    email_disabled_reason: str | None
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


class AgentSettingsResponse(BaseModel):
    desktop_sound_enabled: bool
    desktop_sound_id: str
    desktop_sounds: list[DesktopSoundOption]


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
