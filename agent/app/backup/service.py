"""Export/import of user data (searches, templates, notification target
metadata) as a portable, versioned JSON document.

Secrets (Discord webhook URLs, ntfy topics/tokens, the SMTP password) are
never part of a notification target's non-secret database row, so they are
structurally excluded from export — there is nothing here that could leak
them. Import never overwrites existing data: templates, notification targets
and searches are matched by name (and, for targets, type) and skipped if a
match already exists, matching the "no blind overwrite" requirement.
"""

from __future__ import annotations

import json
from dataclasses import dataclass

from pydantic import ValidationError

from agent.app._version import __version__
from agent.app.backup.schemas import BACKUP_FORMAT_VERSION, BackupFile
from agent.app.core.models import SearchCategory
from agent.app.core.time import to_db_timestamp
from agent.app.storage.database import Database, SearchCreateData, TemplateCreateData


class BackupValidationError(ValueError):
    """The supplied backup document is not a valid, supported backup file."""


@dataclass(frozen=True, slots=True)
class ImportSummary:
    templates_created: int
    templates_skipped: int
    notification_targets_created: int
    notification_targets_skipped: int
    searches_created: int
    searches_skipped: int


async def export_backup(database: Database) -> dict[str, object]:
    templates = await database.list_templates()
    targets = await database.list_notification_targets()
    searches = await database.list_searches()
    target_by_id = {target.id: target for target in targets}
    template_by_id = {template.id: template for template in templates}

    return {
        "format_version": BACKUP_FORMAT_VERSION,
        "app_version": __version__,
        "exported_at": to_db_timestamp(),
        "templates": [{"name": t.name, "body": t.body} for t in templates],
        "notification_targets": [
            {
                "type": target.type,
                "name": target.name,
                "enabled": target.enabled,
                "ntfy_base_url": target.ntfy_base_url,
                "email_address": target.email_address,
            }
            for target in targets
        ],
        "searches": [
            {
                "name": search.name,
                "category": search.category.value,
                "enabled": search.enabled,
                "query": search.query,
                "location": search.location,
                "price_min": str(search.price_min) if search.price_min is not None else None,
                "price_max": str(search.price_max) if search.price_max is not None else None,
                "category_filters": search.category_filters,
                "notify_desktop_sound": search.notify_desktop_sound,
                "notification_targets": [
                    {"type": target_by_id[target_id].type, "name": target_by_id[target_id].name}
                    for target_id in search.notification_target_ids
                    if target_id in target_by_id
                ],
                "default_template_name": (
                    template_by_id[search.default_template_id].name
                    if search.default_template_id in template_by_id
                    else None
                ),
            }
            for search in searches
        ],
    }


def parse_backup_document(raw: bytes | str | dict[str, object]) -> BackupFile:
    if isinstance(raw, dict):
        document = raw
    else:
        try:
            document = json.loads(raw)
        except json.JSONDecodeError as error:
            raise BackupValidationError("Die Backup-Datei ist kein gültiges JSON.") from error
    if not isinstance(document, dict):
        raise BackupValidationError("Die Backup-Datei hat ein ungültiges Format.")
    format_version = document.get("format_version")
    if not isinstance(format_version, int) or format_version != BACKUP_FORMAT_VERSION:
        raise BackupValidationError(
            "Diese Backup-Version wird nicht unterstützt. "
            f"Erwartet: {BACKUP_FORMAT_VERSION}, gefunden: {format_version!r}."
        )
    try:
        return BackupFile.model_validate(document)
    except ValidationError as error:
        raise BackupValidationError("Die Backup-Datei ist ungültig.") from error


async def import_backup(database: Database, backup: BackupFile) -> ImportSummary:
    existing_templates = {template.name: template for template in await database.list_templates()}
    template_name_to_id: dict[str, int] = {t: r.id for t, r in existing_templates.items()}
    templates_created = 0
    templates_skipped = 0
    for entry in backup.templates:
        if entry.name in existing_templates:
            templates_skipped += 1
            continue
        created = await database.create_template(
            TemplateCreateData(name=entry.name, body=entry.body)
        )
        template_name_to_id[entry.name] = created.id
        templates_created += 1

    existing_targets = {
        (target.type, target.name): target for target in await database.list_notification_targets()
    }
    target_ref_to_id: dict[tuple[str, str], int] = {
        key: record.id for key, record in existing_targets.items()
    }
    targets_created = 0
    targets_skipped = 0
    for entry in backup.notification_targets:
        key = (entry.type, entry.name)
        if key in existing_targets:
            targets_skipped += 1
            continue
        created = await database.create_notification_target(
            type=entry.type,
            name=entry.name,
            enabled=entry.enabled,
            ntfy_base_url=entry.ntfy_base_url,
            email_address=entry.email_address,
        )
        target_ref_to_id[key] = created.id
        targets_created += 1

    existing_search_names = {search.name for search in await database.list_searches()}
    searches_created = 0
    searches_skipped = 0
    for entry in backup.searches:
        if entry.name in existing_search_names:
            searches_skipped += 1
            continue
        target_ids = [
            target_ref_to_id[(ref.type, ref.name)]
            for ref in entry.notification_targets
            if (ref.type, ref.name) in target_ref_to_id
        ]
        default_template_id = (
            template_name_to_id.get(entry.default_template_name)
            if entry.default_template_name
            else None
        )
        await database.create_search(
            SearchCreateData(
                name=entry.name,
                category=SearchCategory(entry.category),
                enabled=entry.enabled,
                query=entry.query,
                location=entry.location,
                price_min=entry.price_min,
                price_max=entry.price_max,
                category_filters=entry.category_filters,
                default_template_id=default_template_id,
                notification_target_ids=target_ids,
                notify_desktop_sound=entry.notify_desktop_sound,
            )
        )
        searches_created += 1

    return ImportSummary(
        templates_created=templates_created,
        templates_skipped=templates_skipped,
        notification_targets_created=targets_created,
        notification_targets_skipped=targets_skipped,
        searches_created=searches_created,
        searches_skipped=searches_skipped,
    )
