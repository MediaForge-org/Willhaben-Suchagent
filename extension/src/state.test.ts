import { expect, test, vi } from "vitest";

import {
  ApiDataError,
  ApiHttpError,
  ApiNativeHostError,
  type ApiService,
  ApiTransportError,
} from "./api-contract";
import { loadAgentSnapshot } from "./state";
import { listing, search, settings, status, template } from "./test-fixtures";

test("agent state is online when every local endpoint responds", async () => {
  const api = {
    status: vi.fn(async () => status),
    settings: vi.fn(async () => settings),
    searches: vi.fn(async () => [search]),
    recentListings: vi.fn(async () => [listing]),
    templates: vi.fn(async () => [template]),
    marketplaceOptions: vi.fn(async () => ({ categories: [], locations: [] })),
  } as unknown as ApiService;
  const result = await loadAgentSnapshot(api);
  expect(result.online).toBe(true);
  if (result.online) expect(result.data.searches).toHaveLength(1);
});

test("status success and listings failure remains online", async () => {
  const api = {
    status: vi.fn(async () => status),
    settings: vi.fn(async () => settings),
    searches: vi.fn(async () => [search]),
    recentListings: vi.fn(async () => { throw new Error("Listings unavailable"); }),
    templates: vi.fn(async () => [template]),
    marketplaceOptions: vi.fn(async () => ({ categories: [], locations: [] })),
  } as unknown as ApiService;
  const result = await loadAgentSnapshot(api);
  expect(result.online).toBe(true);
  if (result.online) {
    expect(result.data.status).toEqual(status);
    expect(result.data.listings).toEqual([]);
    expect(result.data.endpointErrors.listings).toBe("Listings unavailable");
  }
});

test("status success and templates failure remains online", async () => {
  const api = {
    status: vi.fn(async () => status),
    settings: vi.fn(async () => settings),
    searches: vi.fn(async () => [search]),
    recentListings: vi.fn(async () => [listing]),
    templates: vi.fn(async () => { throw new Error("Templates unavailable"); }),
    marketplaceOptions: vi.fn(async () => ({ categories: [], locations: [] })),
  } as unknown as ApiService;
  const result = await loadAgentSnapshot(api);
  expect(result.online).toBe(true);
  if (result.online) {
    expect(result.data.listings).toEqual([listing]);
    expect(result.data.templates).toEqual([]);
    expect(result.data.endpointErrors.templates).toBe("Templates unavailable");
  }
});

test("unreachable status endpoint reports the agent offline", async () => {
  const api = {
    status: vi.fn(async () => { throw new ApiTransportError(); }),
    settings: vi.fn(),
    searches: vi.fn(),
    recentListings: vi.fn(),
    templates: vi.fn(),
    marketplaceOptions: vi.fn(),
  } as unknown as ApiService;
  const result = await loadAgentSnapshot(api);
  expect(result).toEqual({
    online: false,
    reason: "agent_unreachable",
    message: "Der Willhaben-Suchagent läuft derzeit nicht.",
  });
});

test("missing native host is distinct from an unreachable agent", async () => {
  const api = {
    status: vi.fn(async () => {
      throw new ApiNativeHostError(
        "not_installed",
        "Lokale Verbindung ist noch nicht eingerichtet.",
      );
    }),
  } as unknown as ApiService;

  await expect(loadAgentSnapshot(api)).resolves.toEqual({
    online: false,
    reason: "native_host_missing",
    message: "Lokale Verbindung ist noch nicht eingerichtet.",
  });
});

test("HTTP error from status endpoint is reachable but partially unavailable", async () => {
  const api = {
    status: vi.fn(async () => { throw new ApiHttpError("Status unavailable", 503); }),
    settings: vi.fn(async () => settings),
    searches: vi.fn(async () => [search]),
    recentListings: vi.fn(async () => [listing]),
    templates: vi.fn(async () => [template]),
    marketplaceOptions: vi.fn(async () => ({ categories: [], locations: [] })),
  } as unknown as ApiService;

  const result = await loadAgentSnapshot(api);

  expect(result.online).toBe(true);
  if (result.online) {
    expect(result.data.status).toBeNull();
    expect(result.data.endpointErrors.status).toBe("Status unavailable");
  }
});

test("data error from status endpoint is reachable but partially unavailable", async () => {
  const api = {
    status: vi.fn(async () => { throw new ApiDataError("Invalid status response"); }),
    settings: vi.fn(async () => settings),
    searches: vi.fn(async () => [search]),
    recentListings: vi.fn(async () => [listing]),
    templates: vi.fn(async () => [template]),
    marketplaceOptions: vi.fn(async () => ({ categories: [], locations: [] })),
  } as unknown as ApiService;

  const result = await loadAgentSnapshot(api);

  expect(result.online).toBe(true);
  if (result.online) {
    expect(result.data.status).toBeNull();
    expect(result.data.endpointErrors.status).toBe("Invalid status response");
  }
});
