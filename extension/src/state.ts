import {
  type ApiService,
  isApiNativeHostError,
  isApiTransportError,
} from "./api-contract";
import type {
  AgentEndpoint,
  AgentSettings,
  AgentSnapshot,
  MarketplaceOptions,
} from "./types";

export type AgentConnection =
  | { online: true; data: AgentSnapshot }
  | {
      online: false;
      reason: "agent_unreachable" | "native_host_missing" | "native_host_start";
      message: string;
    };

export async function loadAgentSnapshot(api: ApiService): Promise<AgentConnection> {
  let status: AgentSnapshot["status"] = null;
  const endpointErrors: Partial<Record<AgentEndpoint, string>> = {};
  try {
    status = await api.status();
  } catch (error) {
    if (isApiNativeHostError(error)) {
      return {
        online: false,
        reason:
          error.reason === "not_installed"
            ? "native_host_missing"
            : "native_host_start",
        message: error.message,
      };
    }
    if (isApiTransportError(error)) {
      return {
        online: false,
        reason: "agent_unreachable",
        message: error.message,
      };
    }
    endpointErrors.status = errorMessage(error);
  }

  const [searchesResult, listingsResult, templatesResult, optionsResult, settingsResult] =
    await Promise.allSettled([
      api.searches(),
      api.recentListings(),
      api.templates(),
      api.marketplaceOptions(),
      api.settings(),
    ]);
  const searches = settledValue(searchesResult, [], "searches", endpointErrors);
  const listings = settledValue(listingsResult, [], "listings", endpointErrors);
  const templates = settledValue(templatesResult, [], "templates", endpointErrors);
  const options = settledValue<MarketplaceOptions>(
    optionsResult,
    { categories: [], locations: [] },
    "options",
    endpointErrors,
  );
  const settings = settledValue<AgentSettings | null>(
    settingsResult,
    null,
    "settings",
    endpointErrors,
  );
  return {
    online: true,
    data: {
      status,
      searches,
      listings,
      templates,
      options,
      settings,
      endpointErrors,
    },
  };
}

function settledValue<T>(
  result: PromiseSettledResult<T>,
  fallback: T,
  endpoint: AgentEndpoint,
  errors: Partial<Record<AgentEndpoint, string>>,
): T {
  if (result.status === "fulfilled") return result.value;
  errors[endpoint] = errorMessage(result.reason);
  return fallback;
}

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : "Daten konnten nicht geladen werden.";
}
