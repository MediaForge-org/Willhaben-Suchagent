SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS searches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL,
    query_json TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    baseline_initialized INTEGER NOT NULL DEFAULT 0
        CHECK (baseline_initialized IN (0, 1)),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_checked_at TEXT,
    last_success_at TEXT,
    consecutive_errors INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_errors >= 0)
);

CREATE INDEX IF NOT EXISTS idx_searches_enabled ON searches(enabled);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_listing_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    price TEXT,
    url TEXT NOT NULL,
    image_url TEXT,
    category TEXT NOT NULL,
    location TEXT,
    attributes_json TEXT NOT NULL DEFAULT '{}',
    first_seen_at TEXT NOT NULL,
    last_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS search_matches (
    search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    first_seen_at TEXT NOT NULL,
    PRIMARY KEY (search_id, listing_id)
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL UNIQUE REFERENCES listings(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_attempt_at TEXT,
    sent_at TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_notifications_status ON notifications(status);
"""
