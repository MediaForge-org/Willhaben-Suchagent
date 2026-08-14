import {
  ApiDataError,
  ApiHttpError,
  ApiNativeHostError,
  type ApiService,
  ApiTransportError,
} from "./api-contract";
import {
  type ApiBrokerRequest,
  isApiBrokerResponse,
} from "./broker-protocol";
import type {
  AgentStatus,
  AgentSettings,
  Listing,
  MarketplaceOptions,
  MessageTemplate,
  Search,
} from "./types";

export interface RuntimeMessenger {
  sendMessage(message: ApiBrokerRequest): Promise<unknown>;
}

export class RuntimeApiClient implements ApiService {
  constructor(private readonly runtime: RuntimeMessenger = browser.runtime) {}

  status = () => this.send<AgentStatus>({ type: "api.status" });
  settings = () => this.send<AgentSettings>({ type: "api.settings.get" });
  updateSettings = (payload: {
    desktop_sound_enabled?: boolean;
    desktop_sound_id?: string;
  }) => this.send<AgentSettings>({ type: "api.settings.update", payload });
  searches = () => this.send<Search[]>({ type: "api.searches.list" });
  recentListings = (limit = 50) =>
    this.send<Listing[]>({ type: "api.listings.recent", limit });
  templates = () => this.send<MessageTemplate[]>({ type: "api.templates.list" });
  marketplaceOptions = () =>
    this.send<MarketplaceOptions>({ type: "api.marketplace.options" });
  createSearch = (payload: Record<string, unknown>) =>
    this.send<Search>({ type: "api.search.create", payload });
  updateSearch = (id: number, payload: Record<string, unknown>) =>
    this.send<Search>({ type: "api.search.update", id, payload });
  deleteSearch = (id: number) =>
    this.send<void>({ type: "api.search.delete", id });
  createTemplate = (payload: { name: string; body: string }) =>
    this.send<MessageTemplate>({ type: "api.template.create", payload });
  updateTemplate = (id: number, payload: { name?: string; body?: string }) =>
    this.send<MessageTemplate>({ type: "api.template.update", id, payload });
  deleteTemplate = (id: number) =>
    this.send<void>({ type: "api.template.delete", id });
  renderTemplate = (templateId: number, listingId: number) =>
    this.send<{ rendered_text: string }>({
      type: "api.template.render",
      templateId,
      listingId,
    });
  testDesktopSound = (soundId?: string) =>
    this.send<{ status: string; message: string }>({
      type: "api.desktop_sound.test",
      ...(soundId === undefined ? {} : { soundId }),
    });

  private async send<T>(message: ApiBrokerRequest): Promise<T> {
    let rawResponse: unknown;
    try {
      rawResponse = await this.runtime.sendMessage(message);
    } catch {
      throw new ApiDataError("Der Extension-Hintergrunddienst antwortet derzeit nicht.");
    }
    if (!isApiBrokerResponse(rawResponse)) {
      throw new ApiDataError("Der Extension-Hintergrunddienst lieferte eine ungültige Antwort.");
    }
    if (rawResponse.ok) return rawResponse.data as T;
    switch (rawResponse.error.kind) {
      case "transport":
        throw new ApiTransportError();
      case "http":
        throw new ApiHttpError(rawResponse.error.message, rawResponse.error.status ?? 500);
      case "data":
      case "broker":
        throw new ApiDataError(rawResponse.error.message);
      case "native_host_missing":
        throw new ApiNativeHostError("not_installed", rawResponse.error.message);
      case "native_host_start":
        throw new ApiNativeHostError("not_startable", rawResponse.error.message);
    }
  }
}
