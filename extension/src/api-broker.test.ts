import { expect, test, vi } from "vitest";

import {
  ApiDataError,
  ApiHttpError,
  ApiNativeHostError,
  type ApiService,
  ApiTransportError,
} from "./api-contract";
import { handleApiBrokerRequest, type BrokerLogger } from "./api-broker";
import { settings } from "./test-fixtures";

const logger: BrokerLogger = { info: vi.fn(), error: vi.fn() };

function mockApi(): ApiService {
  return {
    status: vi.fn(async () => ({ scheduler_running: true } as never)),
    settings: vi.fn(async () => settings),
    updateSettings: vi.fn(async (payload) => ({ ...settings, ...payload })),
    searches: vi.fn(async () => []),
    recentListings: vi.fn(async () => []),
    templates: vi.fn(async () => []),
    marketplaceOptions: vi.fn(async () => ({ categories: [], locations: [] })),
    createSearch: vi.fn(async (payload) => ({ id: 7, ...payload } as never)),
    updateSearch: vi.fn(async (id, payload) => ({ id, ...payload } as never)),
    deleteSearch: vi.fn(async () => undefined),
    createTemplate: vi.fn(async (payload) => ({ id: 3, ...payload } as never)),
    updateTemplate: vi.fn(async (id, payload) => ({ id, ...payload } as never)),
    deleteTemplate: vi.fn(async () => undefined),
    renderTemplate: vi.fn(async () => ({ rendered_text: "Hallo" })),
    testDesktopSound: vi.fn(async () => ({ status: "played", message: "Notify" })),
  };
}

test("background dispatches status, listings and collection operations", async () => {
  const api = mockApi();

  await handleApiBrokerRequest({ type: "api.status" }, api, logger);
  await handleApiBrokerRequest({ type: "api.listings.recent", limit: 1 }, api, logger);
  await handleApiBrokerRequest({ type: "api.searches.list" }, api, logger);
  await handleApiBrokerRequest({ type: "api.templates.list" }, api, logger);
  await handleApiBrokerRequest({ type: "api.marketplace.options" }, api, logger);

  expect(api.status).toHaveBeenCalledOnce();
  expect(api.recentListings).toHaveBeenCalledExactlyOnceWith(1);
  expect(api.searches).toHaveBeenCalledOnce();
  expect(api.templates).toHaveBeenCalledOnce();
  expect(api.marketplaceOptions).toHaveBeenCalledOnce();
});

test("background mediates search CRUD", async () => {
  const api = mockApi();
  const payload = { name: "ThinkPad", category: "marketplace" };

  await handleApiBrokerRequest({ type: "api.search.create", payload }, api, logger);
  await handleApiBrokerRequest(
    { type: "api.search.update", id: 7, payload: { enabled: false } },
    api,
    logger,
  );
  await handleApiBrokerRequest({ type: "api.search.delete", id: 7 }, api, logger);

  expect(api.createSearch).toHaveBeenCalledExactlyOnceWith(payload);
  expect(api.updateSearch).toHaveBeenCalledExactlyOnceWith(7, { enabled: false });
  expect(api.deleteSearch).toHaveBeenCalledExactlyOnceWith(7);
});

test("background mediates template CRUD and rendering", async () => {
  const api = mockApi();
  const template = { name: "Kaufinteresse", body: "Hallo [Name]" };

  await handleApiBrokerRequest({ type: "api.template.create", payload: template }, api, logger);
  await handleApiBrokerRequest(
    { type: "api.template.update", id: 3, payload: { body: "Hallo" } },
    api,
    logger,
  );
  await handleApiBrokerRequest(
    { type: "api.template.render", templateId: 3, listingId: 9 },
    api,
    logger,
  );
  await handleApiBrokerRequest({ type: "api.template.delete", id: 3 }, api, logger);

  expect(api.createTemplate).toHaveBeenCalledExactlyOnceWith(template);
  expect(api.updateTemplate).toHaveBeenCalledExactlyOnceWith(3, { body: "Hallo" });
  expect(api.renderTemplate).toHaveBeenCalledExactlyOnceWith(3, 9);
  expect(api.deleteTemplate).toHaveBeenCalledExactlyOnceWith(3);
});

test("background mediates persistent settings and the selected sound test", async () => {
  const api = mockApi();

  await handleApiBrokerRequest({ type: "api.settings.get" }, api, logger);
  await handleApiBrokerRequest(
    { type: "api.settings.update", payload: { desktop_sound_id: "ping" } },
    api,
    logger,
  );
  await handleApiBrokerRequest(
    { type: "api.desktop_sound.test", soundId: "ping" },
    api,
    logger,
  );

  expect(api.settings).toHaveBeenCalledOnce();
  expect(api.updateSettings).toHaveBeenCalledExactlyOnceWith({
    desktop_sound_id: "ping",
  });
  expect(api.testDesktopSound).toHaveBeenCalledExactlyOnceWith("ping");
});

test("unknown operations and injected top-level URLs are rejected", async () => {
  const api = mockApi();

  const unknown = await handleApiBrokerRequest(
    { type: "api.fetch", url: "https://example.test" },
    api,
    logger,
  );
  const injected = await handleApiBrokerRequest(
    { type: "api.status", url: "https://example.test" },
    api,
    logger,
  );
  const invalidSound = await handleApiBrokerRequest(
    {
      type: "api.settings.update",
      payload: { desktop_sound_id: "unknown" },
    },
    api,
    logger,
  );

  expect(unknown).toMatchObject({ ok: false, error: { kind: "broker" } });
  expect(injected).toMatchObject({ ok: false, error: { kind: "broker" } });
  expect(invalidSound).toMatchObject({ ok: false, error: { kind: "broker" } });
  expect(api.status).not.toHaveBeenCalled();
  expect(api.updateSettings).not.toHaveBeenCalled();
});

test("background serializes native-host, agent, HTTP and data failures separately", async () => {
  const api = mockApi();
  vi.mocked(api.status)
    .mockRejectedValueOnce(
      new ApiNativeHostError("not_installed", "Lokale Verbindung ist noch nicht eingerichtet."),
    )
    .mockRejectedValueOnce(new ApiTransportError())
    .mockRejectedValueOnce(new ApiHttpError("Agent request failed", 503))
    .mockRejectedValueOnce(new ApiDataError("Invalid host response"));

  const responses = [];
  for (let index = 0; index < 4; index += 1) {
    responses.push(await handleApiBrokerRequest({ type: "api.status" }, api, logger));
  }

  expect(responses.map((response) => (response.ok ? "ok" : response.error.kind))).toEqual([
    "native_host_missing",
    "transport",
    "http",
    "data",
  ]);
});
