import { expect, test, vi } from "vitest";

import {
  ApiDataError,
  ApiHttpError,
  ApiNativeHostError,
  type ApiService,
  ApiTransportError,
} from "./api-contract";
import { handleApiBrokerRequest, type BrokerLogger } from "./api-broker";
import { notificationSettings, notificationTargets, settings } from "./test-fixtures";

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
    updateNotificationSettings: vi.fn(async (payload) => ({
      ...notificationSettings,
      ...payload,
    }) as never),
    importSearchUrl: vi.fn(async () => ({
      category_path: "apple/iphone-13-mini-5009987",
      category_label: "Apple → iPhone 13 Mini",
      query: "iphone 13 mini",
      location: null,
      price_min: null,
      price_max: null,
      unsupported_filters: [],
    })),
    notificationTargets: vi.fn(async () => notificationTargets),
    createNotificationTarget: vi.fn(async (payload) => ({ id: 9, ...payload }) as never),
    updateNotificationTarget: vi.fn(async (id, payload) => ({ id, ...payload }) as never),
    deleteNotificationTarget: vi.fn(async () => ({ deleted: true, searches_affected: 0 })),
    testNotificationTarget: vi.fn(async () => ({ status: "sent", message: "Test erfolgreich" })),
    exportBackup: vi.fn(async () => ({ format_version: 1 })),
    importBackup: vi.fn(async () => ({
      templates_created: 0,
      templates_skipped: 0,
      notification_targets_created: 0,
      notification_targets_skipped: 0,
      searches_created: 0,
      searches_skipped: 0,
    })),
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

test("background mediates global notification settings updates", async () => {
  const api = mockApi();

  await handleApiBrokerRequest(
    {
      type: "api.settings.notifications.update",
      payload: { ntfy_timeout_seconds: 15 },
    },
    api,
    logger,
  );

  expect(api.updateNotificationSettings).toHaveBeenCalledExactlyOnceWith({
    ntfy_timeout_seconds: 15,
  });
});

test("malformed notification settings payloads are rejected without dispatch", async () => {
  const api = mockApi();

  const empty = await handleApiBrokerRequest(
    { type: "api.settings.notifications.update", payload: {} },
    api,
    logger,
  );

  expect(empty).toMatchObject({ ok: false, error: { kind: "broker" } });
  expect(api.updateNotificationSettings).not.toHaveBeenCalled();
});

test("background mediates notification target CRUD and per-target test", async () => {
  const api = mockApi();

  await handleApiBrokerRequest({ type: "api.notificationTargets.list" }, api, logger);
  await handleApiBrokerRequest(
    {
      type: "api.notificationTargets.create",
      payload: { type: "ntfy", name: "Maxim iPhone", topic: "x" },
    },
    api,
    logger,
  );
  await handleApiBrokerRequest(
    { type: "api.notificationTargets.update", id: 1, payload: { enabled: false } },
    api,
    logger,
  );
  await handleApiBrokerRequest({ type: "api.notificationTargets.delete", id: 1 }, api, logger);
  await handleApiBrokerRequest({ type: "api.notificationTargets.test", id: 1 }, api, logger);

  expect(api.notificationTargets).toHaveBeenCalledOnce();
  expect(api.createNotificationTarget).toHaveBeenCalledExactlyOnceWith({
    type: "ntfy",
    name: "Maxim iPhone",
    topic: "x",
  });
  expect(api.updateNotificationTarget).toHaveBeenCalledExactlyOnceWith(1, { enabled: false });
  expect(api.deleteNotificationTarget).toHaveBeenCalledExactlyOnceWith(1);
  expect(api.testNotificationTarget).toHaveBeenCalledExactlyOnceWith(1);
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
