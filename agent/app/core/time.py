from datetime import UTC, datetime


def utc_now() -> datetime:
    return datetime.now(UTC)


def to_db_timestamp(value: datetime | None = None) -> str:
    return (value or utc_now()).isoformat()
