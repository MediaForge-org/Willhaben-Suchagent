import { expect, test, vi } from "vitest";

import { ApiClient } from "./api";
import { loadAgentSnapshot } from "./state";
import { listing, search, status, template } from "./test-fixtures";

test("agent state is online when every local endpoint responds", async () => {
  const api = {
    status: vi.fn(async () => status),
    searches: vi.fn(async () => [search]),
    recentListings: vi.fn(async () => [listing]),
    templates: vi.fn(async () => [template]),
    marketplaceOptions: vi.fn(async () => ({ categories: [], locations: [] })),
  } as unknown as ApiClient;
  const result = await loadAgentSnapshot(api);
  expect(result.online).toBe(true);
  if (result.online) expect(result.data.searches).toHaveLength(1);
});

test("agent state stays usable and reports offline without leaking errors", async () => {
  const api = {
    status: vi.fn(async () => { throw new Error("Der Willhaben-Suchagent läuft derzeit nicht."); }),
    searches: vi.fn(), recentListings: vi.fn(), templates: vi.fn(), marketplaceOptions: vi.fn(),
  } as unknown as ApiClient;
  const result = await loadAgentSnapshot(api);
  expect(result).toEqual({ online: false, message: "Der Willhaben-Suchagent läuft derzeit nicht." });
});
