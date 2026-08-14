import type {
  AgentStatus,
  AgentSettings,
  Listing,
  MarketplaceOptions,
  MessageTemplate,
  Search,
} from "./types";

export class ApiError extends Error {
  readonly status?: number;

  constructor(message: string, status?: number) {
    super(message);
    this.status = status;
  }
}

export class ApiTransportError extends ApiError {
  constructor() {
    super("Der Willhaben-Suchagent läuft derzeit nicht.");
    this.name = "ApiTransportError";
  }
}

export class ApiHttpError extends ApiError {
  constructor(message: string, status: number) {
    super(message, status);
    this.name = "ApiHttpError";
  }
}

export class ApiDataError extends ApiError {
  constructor(message: string) {
    super(message);
    this.name = "ApiDataError";
  }
}

export type NativeHostFailure = "not_installed" | "not_startable";

export class ApiNativeHostError extends ApiError {
  constructor(
    public readonly reason: NativeHostFailure,
    message: string,
  ) {
    super(message);
    this.name = "ApiNativeHostError";
  }
}

export function isApiTransportError(error: unknown): error is ApiTransportError {
  return error instanceof ApiTransportError;
}

export function isApiNativeHostError(error: unknown): error is ApiNativeHostError {
  return error instanceof ApiNativeHostError;
}

export interface ApiService {
  status(): Promise<AgentStatus>;
  settings(): Promise<AgentSettings>;
  updateSettings(payload: {
    desktop_sound_enabled?: boolean;
    desktop_sound_id?: string;
  }): Promise<AgentSettings>;
  searches(): Promise<Search[]>;
  recentListings(limit?: number): Promise<Listing[]>;
  templates(): Promise<MessageTemplate[]>;
  marketplaceOptions(): Promise<MarketplaceOptions>;
  createSearch(payload: Record<string, unknown>): Promise<Search>;
  updateSearch(id: number, payload: Record<string, unknown>): Promise<Search>;
  deleteSearch(id: number): Promise<void>;
  createTemplate(payload: { name: string; body: string }): Promise<MessageTemplate>;
  updateTemplate(
    id: number,
    payload: { name?: string; body?: string },
  ): Promise<MessageTemplate>;
  deleteTemplate(id: number): Promise<void>;
  renderTemplate(templateId: number, listingId: number): Promise<{ rendered_text: string }>;
  testDesktopSound(soundId?: string): Promise<{ status: string; message: string }>;
}
