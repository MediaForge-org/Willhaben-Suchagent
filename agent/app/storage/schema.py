SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS message_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

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
    consecutive_errors INTEGER NOT NULL DEFAULT 0 CHECK (consecutive_errors >= 0),
    default_template_id INTEGER REFERENCES message_templates(id) ON DELETE SET NULL,
    notify_ntfy INTEGER NOT NULL DEFAULT 1 CHECK (notify_ntfy IN (0, 1)),
    notify_discord INTEGER NOT NULL DEFAULT 1 CHECK (notify_discord IN (0, 1)),
    notify_email INTEGER NOT NULL DEFAULT 1 CHECK (notify_email IN (0, 1)),
    notify_desktop_sound INTEGER NOT NULL DEFAULT 1 CHECK (notify_desktop_sound IN (0, 1))
);

CREATE INDEX IF NOT EXISTS idx_searches_enabled ON searches(enabled);

CREATE TABLE IF NOT EXISTS listings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    provider_listing_id TEXT NOT NULL UNIQUE,
    title TEXT NOT NULL,
    article_label TEXT NOT NULL DEFAULT 'Artikel',
    article_phrase TEXT NOT NULL DEFAULT 'der Artikel',
    price TEXT,
    url TEXT NOT NULL,
    image_url TEXT,
    category TEXT NOT NULL,
    location TEXT,
    seller_name TEXT,
    seller_type TEXT CHECK (seller_type IS NULL OR seller_type IN ('private', 'commercial')),
    condition TEXT,
    enrichment_status TEXT NOT NULL DEFAULT 'not_requested'
        CHECK (enrichment_status IN ('not_requested', 'enriched', 'partial', 'failed')),
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

CREATE TABLE IF NOT EXISTS channel_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    channel TEXT NOT NULL CHECK (channel IN ('ntfy', 'discord', 'email')),
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed', 'skipped')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_attempt_at TEXT,
    sent_at TEXT,
    last_error TEXT,
    UNIQUE (listing_id, channel)
);

CREATE TABLE IF NOT EXISTS agent_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notification_targets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL CHECK (type IN ('ntfy', 'discord', 'email')),
    name TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1 CHECK (enabled IN (0, 1)),
    ntfy_base_url TEXT,
    email_address TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_notification_targets_type ON notification_targets(type);

CREATE TABLE IF NOT EXISTS search_notification_targets (
    search_id INTEGER NOT NULL REFERENCES searches(id) ON DELETE CASCADE,
    target_id INTEGER NOT NULL REFERENCES notification_targets(id) ON DELETE CASCADE,
    PRIMARY KEY (search_id, target_id)
);

CREATE INDEX IF NOT EXISTS idx_search_notification_targets_target
    ON search_notification_targets(target_id);

CREATE TABLE IF NOT EXISTS notification_deliveries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    listing_id INTEGER NOT NULL REFERENCES listings(id) ON DELETE CASCADE,
    target_id INTEGER NOT NULL REFERENCES notification_targets(id) ON DELETE CASCADE,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed', 'skipped')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK (attempt_count >= 0),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    last_attempt_at TEXT,
    sent_at TEXT,
    last_error TEXT,
    UNIQUE (listing_id, target_id)
);
"""
