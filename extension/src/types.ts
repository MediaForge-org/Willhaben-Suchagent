export interface AgentStatus {
  app_version: string;
  environment: "development" | "test" | "production";
  status: "ok" | "degraded";
  scheduler_running: boolean;
  active_searches: number;
  total_cycle_count: number;
  cycle_interval_seconds: number;
  last_cycle_started_at: string | null;
  next_cycle_due_at: string | null;
  last_cycle_completed_at: string | null;
  last_successful_willhaben_cycle_at: string | null;
  last_provider_errors: Record<string, string>;
  pending_notifications: number;
  failed_notifications: number;
  desktop_sound_enabled: boolean;
  desktop_sound_id: string;
  desktop_sound_available: boolean;
  desktop_sound_disabled_reason: string | null;
}

export interface Search {
  id: number;
  name: string;
  category: "marketplace";
  enabled: boolean;
  query: string;
  location: string | null;
  price_min: string | null;
  price_max: string | null;
  category_filters: Record<string, unknown>;
  default_template_id: number | null;
  baseline_initialized: boolean;
  last_checked_at: string | null;
  last_success_at: string | null;
  consecutive_errors: number;
  notification_target_ids: number[];
  notify_desktop_sound: boolean;
}

export interface Listing {
  listing_id: number;
  provider_listing_id: string;
  title: string;
  article_label: string;
  article_phrase: string;
  price: string | null;
  location: string | null;
  image_url: string | null;
  seller_name: string | null;
  seller_type: "private" | "commercial" | null;
  condition: string | null;
  url: string;
  first_seen_at: string;
  search_ids: number[];
  search_names: string[];
}

export interface MessageTemplate {
  id: number;
  name: string;
  body: string;
  created_at: string;
  updated_at: string;
}

export interface MarketplaceOptions {
  categories: Array<{ label: string; value: string }>;
  locations: Array<{ label: string; value: string }>;
}

export type NotificationTargetType = "ntfy" | "discord" | "email";

export interface NotificationTarget {
  id: number;
  type: NotificationTargetType;
  name: string;
  enabled: boolean;
  configured: boolean;
  ntfy_base_url: string | null;
  ntfy_topic_configured: boolean;
  ntfy_token_configured: boolean;
  discord_webhook_configured: boolean;
  email_address: string | null;
  email_address_masked: string | null;
  usage_count: number;
  created_at: string;
  updated_at: string;
}

export interface NotificationTargetCreate {
  type: NotificationTargetType;
  name: string;
  enabled?: boolean;
  base_url?: string;
  topic?: string;
  token?: string;
  webhook_url?: string;
  email_address?: string;
}

export interface NotificationTargetPatch {
  name?: string;
  enabled?: boolean;
  base_url?: string;
  topic?: string;
  token?: string;
  webhook_url?: string;
  email_address?: string;
}

/** Global, provider-technical settings only — per-destination config lives in
 * notification targets (NotificationTarget) instead. */
export interface GlobalNotificationSettings {
  ntfy_timeout_seconds: number;
  discord_timeout_seconds: number;
  email_smtp_host: string | null;
  email_smtp_port: number;
  email_smtp_username: string | null;
  email_smtp_password_configured: boolean;
  email_from_address: string | null;
  email_encryption: "starttls" | "ssl" | "none";
  email_timeout_seconds: number;
}

export interface GlobalNotificationSettingsPatch {
  ntfy_timeout_seconds?: number;
  discord_timeout_seconds?: number;
  email_smtp_host?: string | null;
  email_smtp_port?: number;
  email_smtp_username?: string | null;
  email_smtp_password?: string;
  email_from_address?: string | null;
  email_encryption?: "starttls" | "ssl" | "none";
  email_timeout_seconds?: number;
}

export interface AgentSettings {
  desktop_sound_enabled: boolean;
  desktop_sound_id: string;
  desktop_sounds: Array<{ id: string; name: string }>;
  notifications: GlobalNotificationSettings | null;
}

export interface ChannelTestResult {
  status: string;
  message: string;
}

/** Opaque, versioned backup document — see agent/app/backup/schemas.py for its shape. */
export interface BackupDocument {
  format_version: number;
  [key: string]: unknown;
}

export interface BackupImportSummary {
  templates_created: number;
  templates_skipped: number;
  notification_targets_created: number;
  notification_targets_skipped: number;
  searches_created: number;
  searches_skipped: number;
}

export interface ImportedSearchDraft {
  category_path: string | null;
  category_label: string | null;
  query: string;
  location: string | null;
  price_min: string | null;
  price_max: string | null;
  unsupported_filters: string[];
}

export interface AgentSnapshot {
  status: AgentStatus | null;
  searches: Search[];
  listings: Listing[];
  templates: MessageTemplate[];
  options: MarketplaceOptions;
  settings: AgentSettings | null;
  notificationTargets: NotificationTarget[];
  endpointErrors: Partial<Record<AgentEndpoint, string>>;
}

export type AgentEndpoint =
  | "status"
  | "searches"
  | "listings"
  | "templates"
  | "options"
  | "settings"
  | "notificationTargets";
