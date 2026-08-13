from collections.abc import AsyncIterator, Callable
from decimal import Decimal
from pathlib import Path

import httpx
import pytest
import pytest_asyncio

try:
    import uvloop
except ImportError:
    uvloop = None

from agent.app.core.config import Settings
from agent.app.core.health import HealthState
from agent.app.core.models import Listing, SearchCategory
from agent.app.core.scheduler import Scheduler
from agent.app.main import create_app
from agent.app.notifications.service import FakeNotificationService
from agent.app.storage.database import Database, SearchCreateData
from agent.app.willhaben.fake_provider import FakeListingProvider

if uvloop is not None:

    def pytest_asyncio_loop_factories(config: pytest.Config, item: pytest.Item):
        """Use uvloop where Uvicorn's platform-specific extra provides it."""

        return {"uvloop": uvloop.new_event_loop}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    return Settings(
        database_path=tmp_path / "test.db",
        app_environment="test",
        scheduler_enabled=False,
        cycle_interval_seconds=60,
        max_concurrent_requests=2,
    )


@pytest_asyncio.fixture
async def database(settings: Settings) -> Database:
    instance = Database(settings.database_path)
    await instance.initialize()
    return instance


@pytest.fixture
def provider() -> FakeListingProvider:
    return FakeListingProvider()


@pytest.fixture
def notifications() -> FakeNotificationService:
    return FakeNotificationService()


@pytest.fixture
def scheduler_factory(
    database: Database,
    provider: FakeListingProvider,
    notifications: FakeNotificationService,
    settings: Settings,
) -> Callable[..., Scheduler]:
    def factory(**overrides: object) -> Scheduler:
        return Scheduler(
            database=database,
            provider=overrides.get("provider", provider),
            notification_service=overrides.get("notification_service", notifications),
            health=overrides.get("health", HealthState()),
            cycle_interval_seconds=float(
                overrides.get("cycle_interval_seconds", settings.cycle_interval_seconds)
            ),
            max_concurrent_requests=int(
                overrides.get("max_concurrent_requests", settings.max_concurrent_requests)
            ),
        )

    return factory


@pytest.fixture
def search_data() -> SearchCreateData:
    return SearchCreateData(
        name="BMW",
        category=SearchCategory.AUTO_MOTOR,
        enabled=True,
        query="BMW",
        location="Wien",
        price_min=Decimal("1000"),
        price_max=Decimal("50000"),
        category_filters={"model": "340i"},
    )


@pytest.fixture
def listing_factory() -> Callable[..., Listing]:
    def factory(provider_listing_id: str = "listing-1", **overrides: object) -> Listing:
        values: dict[str, object] = {
            "provider_listing_id": provider_listing_id,
            "title": f"Listing {provider_listing_id}",
            "price": Decimal("19999.99"),
            "url": f"https://example.test/{provider_listing_id}",
            "image_url": f"https://example.test/{provider_listing_id}.jpg",
            "category": SearchCategory.AUTO_MOTOR,
            "location": "Wien",
            "attributes": {"mileage_km": 75000},
        }
        values.update(overrides)
        return Listing.model_validate(values)

    return factory


@pytest_asyncio.fixture
async def api_client(
    settings: Settings,
    provider: FakeListingProvider,
    notifications: FakeNotificationService,
) -> AsyncIterator[httpx.AsyncClient]:
    app = create_app(settings, provider, notifications)
    async with app.router.lifespan_context(app):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
            yield client
