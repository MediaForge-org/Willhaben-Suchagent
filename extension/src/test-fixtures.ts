import type {
  AgentSettings,
  AgentStatus,
  Listing,
  MessageTemplate,
  Search,
} from "./types";

export const status: AgentStatus = {
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

export const settings: AgentSettings = {
  desktop_sound_enabled: true,
  desktop_sound_id: "notify",
  desktop_sounds: [
    { id: "notify", name: "Notify" },
    { id: "ping", name: "Ping" },
    { id: "pop", name: "Pop" },
  ],
};

export const template: MessageTemplate = {
  id: 2,
  name: "Kaufinteresse",
  body: "Hallo [Name],\n\nist [Artikel] verfügbar?",
  created_at: "2026-08-13T09:00:00Z",
  updated_at: "2026-08-13T09:00:00Z",
};
