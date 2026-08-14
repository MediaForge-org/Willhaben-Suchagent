import {
  ApiDataError,
  ApiHttpError,
  ApiNativeHostError,
  type ApiService,
  ApiTransportError,
} from "./api-contract";
import {
  type ApiBrokerRequest,
  type ApiBrokerResponse,
  isNativeResponseEnvelope,
  type NativeRequestEnvelope,
} from "./broker-protocol";
import type {
  AgentStatus,
  AgentSettings,
  Listing,
  MarketplaceOptions,
  MessageTemplate,
  Search,
} from "./types";

export const NATIVE_HOST_NAME = "at.willhaben_suchagent.bridge";
const RESPONSE_TIMEOUT_MS = 15_000;

interface NativeEvent<Argument> {
  addListener(listener: (argument: Argument) => void): void;
  removeListener(listener: (argument: Argument) => void): void;
}

export interface NativePort {
  error?: Error;
  postMessage(message: NativeRequestEnvelope): void;
  disconnect(): void;
  onMessage: NativeEvent<unknown>;
  onDisconnect: NativeEvent<NativePort>;
}

export interface NativeConnector {
  connectNative(application: string): NativePort;
}

interface PendingRequest {
  resolve(response: ApiBrokerResponse): void;
  reject(error: Error): void;
  timeout: ReturnType<typeof setTimeout>;
}

export class NativeApiClient implements ApiService {
  private port: NativePort | null = null;
  private nextRequestId = 1;
  private readonly pending = new Map<string, PendingRequest>();

  constructor(private readonly runtime: NativeConnector = defaultNativeConnector()) {}

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
  deleteSearch = (id: number) => this.send<void>({ type: "api.search.delete", id });
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

  disconnect(): void {
    this.port?.disconnect();
    this.releasePort(this.port, new ApiDataError("Native Verbindung wurde beendet."));
  }

  private async send<T>(request: ApiBrokerRequest): Promise<T> {
    const response = await this.sendRequest(request);
    if (response.ok) return response.data as T;
    switch (response.error.kind) {
      case "transport":
        throw new ApiTransportError();
      case "http":
        throw new ApiHttpError(response.error.message, response.error.status ?? 500);
      case "native_host_missing":
        throw new ApiNativeHostError("not_installed", response.error.message);
      case "native_host_start":
        throw new ApiNativeHostError("not_startable", response.error.message);
      case "data":
      case "broker":
        throw new ApiDataError(response.error.message);
    }
  }

  private sendRequest(request: ApiBrokerRequest): Promise<ApiBrokerResponse> {
    let port: NativePort;
    try {
      port = this.ensurePort();
    } catch (error) {
      return Promise.reject(classifyNativeConnectionError(error));
    }
    const requestId = String(this.nextRequestId++);
    return new Promise<ApiBrokerResponse>((resolve, reject) => {
      const timeout = setTimeout(() => {
        this.pending.delete(requestId);
        reject(new ApiDataError("Der Native Host hat nicht rechtzeitig geantwortet."));
      }, RESPONSE_TIMEOUT_MS);
      this.pending.set(requestId, { resolve, reject, timeout });
      try {
        port.postMessage({ requestId, request });
      } catch (error) {
        clearTimeout(timeout);
        this.pending.delete(requestId);
        this.releasePort(port, classifyNativeConnectionError(error));
      }
    });
  }

  private ensurePort(): NativePort {
    if (this.port) return this.port;
    const port = this.runtime.connectNative(NATIVE_HOST_NAME);
    port.onMessage.addListener(this.handleMessage);
    port.onDisconnect.addListener(this.handleDisconnect);
    this.port = port;
    return port;
  }

  private readonly handleMessage = (rawMessage: unknown): void => {
    if (!isNativeResponseEnvelope(rawMessage)) {
      this.failAll(new ApiDataError("Der Native Host lieferte eine ungültige Antwort."));
      return;
    }
    const request = this.pending.get(rawMessage.requestId);
    if (!request) return;
    clearTimeout(request.timeout);
    this.pending.delete(rawMessage.requestId);
    request.resolve(rawMessage.response);
  };

  private readonly handleDisconnect = (port: NativePort): void => {
    this.releasePort(port, classifyNativeConnectionError(port.error));
  };

  private releasePort(port: NativePort | null, error: Error): void {
    if (!port || this.port !== port) return;
    port.onMessage.removeListener(this.handleMessage);
    port.onDisconnect.removeListener(this.handleDisconnect);
    this.port = null;
    this.failAll(error);
  }

  private failAll(error: Error): void {
    for (const request of this.pending.values()) {
      clearTimeout(request.timeout);
      request.reject(error);
    }
    this.pending.clear();
  }
}

function defaultNativeConnector(): NativeConnector {
  return {
    connectNative: (application) =>
      browser.runtime.connectNative(application) as unknown as NativePort,
  };
}

function classifyNativeConnectionError(error: unknown): ApiNativeHostError {
  const description = error instanceof Error ? error.message.toLowerCase() : "";
  const missing =
    description.includes("no such native application") ||
    description.includes("not found") ||
    description.includes("could not find") ||
    description.includes("file_not_found");
  return new ApiNativeHostError(
    missing ? "not_installed" : "not_startable",
    missing
      ? "Lokale Verbindung ist noch nicht eingerichtet."
      : "Lokale Verbindung konnte nicht gestartet werden.",
  );
}
