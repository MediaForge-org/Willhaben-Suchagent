from decimal import Decimal
from pathlib import Path

import pytest

from agent.app.backup.schemas import BACKUP_FORMAT_VERSION
from agent.app.backup.service import (
    BackupValidationError,
    export_backup,
    import_backup,
    parse_backup_document,
)
from agent.app.core.models import SearchCategory
from agent.app.storage.database import Database, SearchCreateData, TemplateCreateData


async def _database(tmp_path: Path) -> Database:
    database = Database(tmp_path / "backup.db")
    await database.initialize()
    return database


async def _populated_database(tmp_path: Path) -> Database:
    database = await _database(tmp_path)
    template = await database.create_template(
        TemplateCreateData(name="Kurzform", body="Kurze Nachricht!")
    )
    ntfy = await database.create_notification_target(
        type="ntfy", name="Maxim iPhone", ntfy_base_url="https://ntfy.sh"
    )
    discord = await database.create_notification_target(type="discord", name="#willhaben")
    await database.create_search(
        SearchCreateData(
            name="ThinkPad",
            category=SearchCategory.MARKETPLACE,
            enabled=True,
            query="thinkpad",
            location="Wien",
            price_min=Decimal("50"),
            price_max=Decimal("500"),
            category_filters={"categoryPath": "elektronik/notebooks"},
            default_template_id=template.id,
            notification_target_ids=[ntfy.id, discord.id],
            notify_desktop_sound=True,
        )
    )
    return database


@pytest.mark.asyncio
async def test_export_contains_no_secret_fields(tmp_path: Path) -> None:
    database = await _populated_database(tmp_path)

    document = await export_backup(database)

    serialized = str(document)
    for target in document["notification_targets"]:
        assert set(target) == {"type", "name", "enabled", "ntfy_base_url", "email_address"}
    assert "topic" not in serialized
    assert "token" not in serialized
    assert "webhook" not in serialized
    assert "password" not in serialized


@pytest.mark.asyncio
async def test_export_import_roundtrip_recreates_searches_templates_and_target_links(
    tmp_path: Path,
) -> None:
    source = await _populated_database(tmp_path / "source")
    document = await export_backup(source)

    target = await _database(tmp_path / "target")
    backup = parse_backup_document(document)
    summary = await import_backup(target, backup)

    assert summary.templates_created == 1
    assert summary.notification_targets_created == 2
    assert summary.searches_created == 1

    searches = await target.list_searches()
    assert len(searches) == 1
    search = searches[0]
    assert search.name == "ThinkPad"
    assert search.query == "thinkpad"
    assert search.price_min == Decimal("50")
    assert search.price_max == Decimal("500")
    assert search.category_filters == {"categoryPath": "elektronik/notebooks"}
    assert len(search.notification_target_ids) == 2

    targets = await target.list_notification_targets()
    assert {(t.type, t.name) for t in targets} == {
        ("ntfy", "Maxim iPhone"),
        ("discord", "#willhaben"),
    }

    templates = await target.list_templates()
    imported_template = next(t for t in templates if t.name == "Kurzform")
    assert search.default_template_id == imported_template.id


@pytest.mark.asyncio
async def test_import_skips_existing_templates_targets_and_searches_without_overwriting(
    tmp_path: Path,
) -> None:
    source = await _populated_database(tmp_path)
    document = await export_backup(source)
    backup = parse_backup_document(document)

    # Import into the very same database: everything already exists by name.
    summary = await import_backup(source, backup)

    assert summary.templates_created == 0
    assert summary.templates_skipped == 2  # seeded default + "Kurzform"
    assert summary.notification_targets_created == 0
    assert summary.notification_targets_skipped == 2
    assert summary.searches_created == 0
    assert summary.searches_skipped == 1
    # Nothing duplicated, nothing overwritten.
    assert len(await source.list_searches()) == 1
    assert len(await source.list_templates()) == 2  # seeded default + "Kurzform"
    assert len(await source.list_notification_targets()) == 2


def test_parse_rejects_broken_json() -> None:
    with pytest.raises(BackupValidationError, match="gültiges JSON"):
        parse_backup_document("{not valid json")


def test_parse_rejects_wrong_format_version() -> None:
    with pytest.raises(BackupValidationError, match="Backup-Version"):
        parse_backup_document({"format_version": 999, "searches": []})


def test_parse_rejects_missing_format_version() -> None:
    with pytest.raises(BackupValidationError, match="Backup-Version"):
        parse_backup_document({"searches": []})


def test_parse_ignores_unknown_fields_for_forward_compatibility() -> None:
    backup = parse_backup_document(
        {
            "format_version": BACKUP_FORMAT_VERSION,
            "app_version": "1.0.0",
            "exported_at": "2026-08-17T00:00:00Z",
            "templates": [],
            "notification_targets": [],
            "searches": [],
            "some_future_field": {"nested": True},
        }
    )
    assert backup.format_version == BACKUP_FORMAT_VERSION


def test_parse_rejects_search_referencing_unsupported_category() -> None:
    with pytest.raises(BackupValidationError):
        parse_backup_document(
            {
                "format_version": BACKUP_FORMAT_VERSION,
                "searches": [{"name": "Autos", "category": "auto_motor"}],
            }
        )


@pytest.mark.asyncio
async def test_import_reuses_existing_target_when_linking_a_search(tmp_path: Path) -> None:
    database = await _database(tmp_path)
    existing = await database.create_notification_target(type="email", name="Papa")
    backup = parse_backup_document(
        {
            "format_version": BACKUP_FORMAT_VERSION,
            "notification_targets": [{"type": "email", "name": "Papa"}],
            "searches": [
                {
                    "name": "Fahrräder",
                    "notification_targets": [{"type": "email", "name": "Papa"}],
                }
            ],
        }
    )

    summary = await import_backup(database, backup)

    assert summary.notification_targets_skipped == 1
    searches = await database.list_searches()
    assert searches[0].notification_target_ids == [existing.id]
