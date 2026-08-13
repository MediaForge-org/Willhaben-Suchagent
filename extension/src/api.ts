import type {
  AgentStatus,
  Listing,
  MarketplaceOptions,
  MessageTemplate,
  Search,
} from "./types";

export const API_BASE_URL = "http://127.0.0.1:8000";

export class ApiError extends Error {
  readonly status?: number;

  constructor(
    message: string,
    status?: number,
  ) {
    super(message);
    this.status = status;
  }
}

export class ApiClient {
  constructor(
    private readonly baseUrl = API_BASE_URL,
    private readonly request: typeof fetch = fetch,
  ) {}

  private async call<T>(path: string, init?: RequestInit): Promise<T> {
    let response: Response;
    try {
      const headers = new Headers(init?.headers);
      if (init?.body) headers.set("Content-Type", "application/json");
      response = await this.request(`${this.baseUrl}${path}`, {
        ...init,
        headers,
      });
    } catch {
      throw new ApiError("Der Willhaben-Suchagent läuft derzeit nicht.");
    }
    if (!response.ok) {
      let message = "Die Anfrage konnte nicht ausgeführt werden.";
      try {
        const body = (await response.json()) as { detail?: string | Array<{ msg: string }> };
        if (typeof body.detail === "string") message = body.detail;
        else if (Array.isArray(body.detail)) message = body.detail.map((item) => item.msg).join(" ");
      } catch {
        // A concise user-facing fallback is preferable to exposing a transport error.
      }
      throw new ApiError(message, response.status);
    }
    if (response.status === 204) return undefined as T;
    return (await response.json()) as T;
  }

  status = () => this.call<AgentStatus>("/api/v1/status");
  searches = () => this.call<Search[]>("/api/v1/searches");
  recentListings = (limit = 50) => this.call<Listing[]>(`/api/v1/listings/recent?limit=${limit}`);
  templates = () => this.call<MessageTemplate[]>("/api/v1/templates");
  marketplaceOptions = () => this.call<MarketplaceOptions>("/api/v1/marketplace/options");

  createSearch(payload: Record<string, unknown>) {
    return this.call<Search>("/api/v1/searches", { method: "POST", body: JSON.stringify(payload) });
  }
  updateSearch(id: number, payload: Record<string, unknown>) {
    return this.call<Search>(`/api/v1/searches/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
  }
  deleteSearch(id: number) {
    return this.call<void>(`/api/v1/searches/${id}`, { method: "DELETE" });
  }
  createTemplate(payload: { name: string; body: string }) {
    return this.call<MessageTemplate>("/api/v1/templates", { method: "POST", body: JSON.stringify(payload) });
  }
  updateTemplate(id: number, payload: { name?: string; body?: string }) {
    return this.call<MessageTemplate>(`/api/v1/templates/${id}`, { method: "PATCH", body: JSON.stringify(payload) });
  }
  deleteTemplate(id: number) {
    return this.call<void>(`/api/v1/templates/${id}`, { method: "DELETE" });
  }
  renderTemplate(templateId: number, listingId: number) {
    return this.call<{ rendered_text: string }>(`/api/v1/templates/${templateId}/render`, {
      method: "POST",
      body: JSON.stringify({ listing_id: listingId }),
    });
  }
}
