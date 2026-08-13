import { ApiClient } from "./api";
import type { AgentSnapshot } from "./types";

export type AgentConnection =
  | { online: true; data: AgentSnapshot }
  | { online: false; message: string };

export async function loadAgentSnapshot(api: ApiClient): Promise<AgentConnection> {
  try {
    const [status, searches, listings, templates, options] = await Promise.all([
      api.status(),
      api.searches(),
      api.recentListings(),
      api.templates(),
      api.marketplaceOptions(),
    ]);
    return { online: true, data: { status, searches, listings, templates, options } };
  } catch (error) {
    return {
      online: false,
      message: error instanceof Error ? error.message : "Der Willhaben-Suchagent läuft derzeit nicht.",
    };
  }
}
