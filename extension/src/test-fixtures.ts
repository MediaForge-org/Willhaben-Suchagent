import type {
  AgentSettings,
  AgentStatus,
  GlobalNotificationSettings,
  Listing,
  MessageTemplate,
  NotificationTarget,
  Search,
} from "./types";

export const status: AgentStatus = {
  app_version: "1.0.0",
  environment: "development",
  status: "ok",
  scheduler_running: true,
  active_searches: 1,
  total_cycle_count: 4,
  cycle_interval_seconds: 60,
  last_cycle_started_at: "2026-08-13T10:00:00Z",
  next_cycle_due_at: "2026-08-13T10:01:00Z",
  last_cycle_completed_at: "2026-08-13T10:00:01Z",
  last_successful_willhaben_cycle_at: "2026-08-13T10:00:01Z",
  last_provider_errors: {},
  pending_notifications: 0,
  failed_notifications: 0,
  desktop_sound_enabled: true,
  desktop_sound_id: "notify",
  desktop_sound_available: true,
  desktop_sound_disabled_reason: null,
};

export const search: Search = {
  id: 4,
  name: "ThinkPad in Wien",
  category: "marketplace",
  enabled: true,
  query: "ThinkPad",
  location: "Wien",
  price_min: "100",
  price_max: "1200",
  category_filters: { marketplace_category: "computer-software-5824" },
  default_template_id: 2,
  baseline_initialized: true,
  last_checked_at: "2026-08-13T10:00:00Z",
  last_success_at: "2026-08-13T10:00:00Z",
  consecutive_errors: 0,
  notification_target_ids: [1],
  notify_desktop_sound: true,
};

export const listing: Listing = {
  listing_id: 9,
  provider_listing_id: "123",
  title: "Lenovo ThinkPad T14 G3 | i7 32GB",
  article_label: "Lenovo ThinkPad T14 G3",
  article_phrase: "das Lenovo ThinkPad T14 G3",
  price: "465",
  location: "Wien",
  image_url: null,
  seller_name: "Max",
  seller_type: "private",
  condition: "Sehr gut",
  url: "https://www.willhaben.at/iad/object/123",
  first_seen_at: "2026-08-13T10:00:00Z",
  search_ids: [4],
  search_names: ["ThinkPad in Wien"],
};

export const notificationSettings: GlobalNotificationSettings = {
  ntfy_timeout_seconds: 10,
  discord_timeout_seconds: 10,
  email_smtp_host: null,
  email_smtp_port: 587,
  email_smtp_username: null,
  email_smtp_password_configured: false,
  email_from_address: null,
  email_encryption: "starttls",
  email_timeout_seconds: 10,
};

export const settings: AgentSettings = {
  desktop_sound_enabled: true,
  desktop_sound_id: "notify",
  desktop_sounds: [
    { id: "notify", name: "Notify" },
    { id: "ping", name: "Ping" },
    { id: "pop", name: "Pop" },
  ],
  notifications: notificationSettings,
};

export const ntfyTarget: NotificationTarget = {
  id: 1,
  type: "ntfy",
  name: "Maxim iPhone",
  enabled: true,
  configured: true,
  ntfy_base_url: "https://ntfy.sh",
  ntfy_topic_configured: true,
  ntfy_token_configured: false,
  discord_webhook_configured: false,
  email_address: null,
  email_address_masked: null,
  usage_count: 0,
  created_at: "2026-08-13T09:00:00Z",
  updated_at: "2026-08-13T09:00:00Z",
};

export const discordTarget: NotificationTarget = {
  id: 2,
  type: "discord",
  name: "Papa – Willhaben",
  enabled: true,
  configured: true,
  ntfy_base_url: null,
  ntfy_topic_configured: false,
  ntfy_token_configured: false,
  discord_webhook_configured: true,
  email_address: null,
  email_address_masked: null,
  usage_count: 0,
  created_at: "2026-08-13T09:00:00Z",
  updated_at: "2026-08-13T09:00:00Z",
};

export const emailTarget: NotificationTarget = {
  id: 3,
  type: "email",
  name: "Papa",
  enabled: true,
  configured: false,
  ntfy_base_url: null,
  ntfy_topic_configured: false,
  ntfy_token_configured: false,
  discord_webhook_configured: false,
  email_address: "papa@gmail.com",
  email_address_masked: "p***@gmail.com",
  usage_count: 0,
  created_at: "2026-08-13T09:00:00Z",
  updated_at: "2026-08-13T09:00:00Z",
};

export const notificationTargets: NotificationTarget[] = [ntfyTarget, discordTarget, emailTarget];

export const template: MessageTemplate = {
  id: 2,
  name: "Kaufinteresse",
  body: "Hallo [Name],\n\nist [Artikel] verfügbar?",
  created_at: "2026-08-13T09:00:00Z",
  updated_at: "2026-08-13T09:00:00Z",
};
