from pathlib import Path

import pytest

from agent.app.core.models import SearchCategory
from agent.app.core.secret_store import SecretStore
from agent.app.notifications.target_migration import migrate_legacy_notification_settings
from agent.app.storage.database import Database, SearchCreateData


@pytest.fixture
def secret_store(tmp_path: Path) -> SecretStore:
    return SecretStore(tmp_path / "secrets.json")


async def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "migrate.db")
    await database.initialize()
    return database


@pytest.mark.asyncio
async def test_migration_creates_default_targets_from_legacy_global_config(
    tmp_path: Path, secret_store: SecretStore
) -> None:
    database = await _database(tmp_path)
    await database.seed_legacy_agent_settings(
        {
            "ntfy_enabled": "1",
            "ntfy_base_url": "https://ntfy.sh",
            "ntfy_topic": "legacy-topic",
            "discord_enabled": "1",
            "email_enabled": "1",
            "email_to_address": "legacy@example.test",
        }
    )
    secret_store.set_many(
        {
            "ntfy_token": "legacy-token",
            "discord_webhook_url": "https://discord.com/api/webhooks/123456789012345678/legacy",
        }
    )

    await migrate_legacy_notification_settings(database, secret_store)

    targets = await database.list_notification_targets()
    assert {target.type for target in targets} == {"ntfy", "discord", "email"}
    ntfy_target = next(target for target in targets if target.type == "ntfy")
    email_target = next(target for target in targets if target.type == "email")
    assert ntfy_target.name == "Standard Push"
    assert email_target.email_address == "legacy@example.test"

    secrets = secret_store.load()
    assert secrets[f"ntfy_target_{ntfy_target.id}_topic"] == "legacy-topic"
    assert secrets[f"ntfy_target_{ntfy_target.id}_token"] == "legacy-token"
    discord_target = next(target for target in targets if target.type == "discord")
    assert (
        secrets[f"discord_target_{discord_target.id}_webhook_url"]
        == "https://discord.com/api/webhooks/123456789012345678/legacy"
    )


@pytest.mark.asyncio
async def test_existing_searches_keep_their_notifications_after_migration(
    tmp_path: Path, secret_store: SecretStore
) -> None:
    database = await _database(tmp_path)
    await database.seed_legacy_agent_settings(
        {"ntfy_enabled": "1", "ntfy_base_url": "https://ntfy.sh", "ntfy_topic": "legacy-topic"}
    )
    secret_store.set_many({"ntfy_token": "legacy-token"})

    # A pre-M7 search, created directly with the legacy notify_ntfy=1 column value
    # (the new SearchCreateData no longer exposes it, so simulate the pre-migration
    # database state with a raw write, exactly like an upgraded on-disk database).
    search = await database.create_search(
        SearchCreateData(
            name="ThinkPad",
            category=SearchCategory.MARKETPLACE,
            enabled=True,
            query="ThinkPad",
            location=None,
            price_min=None,
            price_max=None,
            category_filters={},
        )
    )
    await database.raw_execute(
        "UPDATE searches SET notify_ntfy = 1, notify_discord = 0, notify_email = 0 WHERE id = ?",
        (search.id,),
    )

    await migrate_legacy_notification_settings(database, secret_store)

    reloaded = await database.get_search(search.id)
    assert reloaded is not None
    targets = await database.list_notification_targets()
    ntfy_target = next(target for target in targets if target.type == "ntfy")
    assert reloaded.notification_target_ids == [ntfy_target.id]


@pytest.mark.asyncio
async def test_migration_never_touches_baseline_or_listings(
    tmp_path: Path, secret_store: SecretStore
) -> None:
    database = await _database(tmp_path)
    await database.seed_legacy_agent_settings(
        {"ntfy_enabled": "1", "ntfy_base_url": "https://ntfy.sh", "ntfy_topic": "t"}
    )
    secret_store.set_many({"ntfy_token": "tok"})
    search = await database.create_search(
        SearchCreateData(
            name="BMW",
            category=SearchCategory.AUTO_MOTOR,
            enabled=True,
            query="BMW",
            location=None,
            price_min=None,
            price_max=None,
            category_filters={},
        )
    )
    await database.persist_cycle_results([(search, [])])
    baseline_before = (await database.get_search(search.id)).baseline_initialized  # type: ignore[union-attr]
    counts_before = await database.status_counts()

    await migrate_legacy_notification_settings(database, secret_store)

    baseline_after = (await database.get_search(search.id)).baseline_initialized  # type: ignore[union-attr]
    counts_after = await database.status_counts()
    assert baseline_after == baseline_before
    assert counts_after == counts_before


@pytest.mark.asyncio
async def test_migration_is_idempotent_and_never_duplicates_targets(
    tmp_path: Path, secret_store: SecretStore
) -> None:
    database = await _database(tmp_path)
    await database.seed_legacy_agent_settings(
        {"ntfy_enabled": "1", "ntfy_base_url": "https://ntfy.sh", "ntfy_topic": "t"}
    )
    secret_store.set_many({"ntfy_token": "tok"})

    await migrate_legacy_notification_settings(database, secret_store)
    await migrate_legacy_notification_settings(database, secret_store)

    targets = await database.list_notification_targets()
    assert len(targets) == 1


@pytest.mark.asyncio
async def test_no_legacy_config_creates_no_targets(
    tmp_path: Path, secret_store: SecretStore
) -> None:
    database = await _database(tmp_path)

    await migrate_legacy_notification_settings(database, secret_store)

    assert await database.list_notification_targets() == []


@pytest.mark.asyncio
async def test_migration_does_not_run_if_targets_already_exist(
    tmp_path: Path, secret_store: SecretStore
) -> None:
    database = await _database(tmp_path)
    await database.create_notification_target(type="ntfy", name="Manually created")
    await database.seed_legacy_agent_settings(
        {"ntfy_enabled": "1", "ntfy_base_url": "https://ntfy.sh", "ntfy_topic": "should-be-ignored"}
    )

    await migrate_legacy_notification_settings(database, secret_store)

    targets = await database.list_notification_targets()
    assert len(targets) == 1
    assert targets[0].name == "Manually created"
