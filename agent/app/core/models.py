from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, model_validator


class SearchCategory(StrEnum):
    MARKETPLACE = "marketplace"
    AUTO_MOTOR = "auto_motor"
    REAL_ESTATE = "real_estate"
    JOBS = "jobs"


class SearchDefinition(BaseModel):
    """Provider-independent search definition with extensible category filters."""

    model_config = ConfigDict(extra="forbid")

    id: int
    name: str = Field(min_length=1, max_length=200)
    category: SearchCategory
    enabled: bool = True
    query: str = Field(default="", max_length=500)
    location: str | None = Field(default=None, max_length=300)
    price_min: Decimal | None = Field(default=None, ge=0)
    price_max: Decimal | None = Field(default=None, ge=0)
    category_filters: dict[str, Any] = Field(default_factory=dict)
    baseline_initialized: bool = False
    created_at: datetime
    updated_at: datetime
    last_checked_at: datetime | None = None
    last_success_at: datetime | None = None
    consecutive_errors: int = 0

    @model_validator(mode="after")
    def validate_price_range(self) -> SearchDefinition:
        if self.price_min is not None and self.price_max is not None:
            if self.price_min > self.price_max:
                raise ValueError("price_min must not exceed price_max")
        return self


class Listing(BaseModel):
    """Normalized listing returned by any provider implementation."""

    model_config = ConfigDict(extra="forbid")

    provider_listing_id: str = Field(min_length=1, max_length=300)
    title: str = Field(min_length=1, max_length=1000)
    price: Decimal | None = Field(default=None, ge=0)
    url: HttpUrl
    image_url: HttpUrl | None = None
    category: SearchCategory
    location: str | None = Field(default=None, max_length=500)
    attributes: dict[str, Any] = Field(default_factory=dict)
