export interface AgentStatus {
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

export interface AgentSettings {
  desktop_sound_enabled: boolean;
  desktop_sound_id: string;
  desktop_sounds: Array<{ id: string; name: string }>;
}

export interface AgentSnapshot {
  status: AgentStatus | null;
  searches: Search[];
  listings: Listing[];
  templates: MessageTemplate[];
  options: MarketplaceOptions;
  settings: AgentSettings | null;
  endpointErrors: Partial<Record<AgentEndpoint, string>>;
}

export type AgentEndpoint =
  | "status"
  | "searches"
  | "listings"
  | "templates"
  | "options"
  | "settings";
