import { expect, test, vi } from "vitest";

import {
  ApiDataError,
  ApiHttpError,
  ApiNativeHostError,
  ApiTransportError,
} from "./api-contract";
import { RuntimeApiClient } from "./runtime-api";
import { status } from "./test-fixtures";

test("UI status request is sent through runtime messaging", async () => {
  const runtime = {
    sendMessage: vi.fn(async () => ({ ok: true, data: status })),
  };
  const api = new RuntimeApiClient(runtime);

  await expect(api.status()).resolves.toEqual(status);
  expect(runtime.sendMessage).toHaveBeenCalledExactlyOnceWith({ type: "api.status" });
});

test("runtime client reconstructs transport, HTTP and data errors", async () => {
  const sendMessage = vi
    .fn()
    .mockResolvedValueOnce({
      ok: false,
      error: { kind: "transport", message: "Agent unavailable" },
    })
    .mockResolvedValueOnce({
      ok: false,
      error: { kind: "http", message: "Request failed", status: 503 },
    })
    .mockResolvedValueOnce({
      ok: false,
      error: { kind: "data", message: "Invalid response" },
    });
  const api = new RuntimeApiClient({ sendMessage });

  await expect(api.status()).rejects.toBeInstanceOf(ApiTransportError);
  await expect(api.status()).rejects.toBeInstanceOf(ApiHttpError);
  await expect(api.status()).rejects.toBeInstanceOf(ApiDataError);
});

test("runtime messaging failure is not misclassified as agent transport failure", async () => {
  const api = new RuntimeApiClient({
    sendMessage: vi.fn(async () => { throw new Error("No receiving end"); }),
  });

  await expect(api.status()).rejects.toBeInstanceOf(ApiDataError);
  await expect(api.status()).rejects.not.toBeInstanceOf(ApiTransportError);
});

test("runtime client preserves native-host installation failures", async () => {
  const api = new RuntimeApiClient({
    sendMessage: vi.fn(async () => ({
      ok: false,
      error: {
        kind: "native_host_missing",
        message: "Lokale Verbindung ist noch nicht eingerichtet.",
      },
    })),
  });

  await expect(api.status()).rejects.toMatchObject({
    reason: "not_installed",
  } satisfies Partial<ApiNativeHostError>);
  await expect(api.status()).rejects.not.toBeInstanceOf(ApiTransportError);
});

test("all UI API capabilities map to fixed broker operations", async () => {
  const sendMessage = vi.fn(async (_message: unknown) => ({ ok: true, data: null }));
  const api = new RuntimeApiClient({ sendMessage });

  await api.searches();
  await api.settings();
  await api.updateSettings({ desktop_sound_enabled: false, desktop_sound_id: "ping" });
  await api.recentListings(12);
  await api.templates();
  await api.marketplaceOptions();
  await api.createSearch({ name: "ThinkPad" });
  await api.updateSearch(4, { enabled: false });
  await api.deleteSearch(4);
  await api.createTemplate({ name: "Kauf", body: "Hallo" });
  await api.updateTemplate(3, { body: "Servus" });
  await api.deleteTemplate(3);
  await api.renderTemplate(3, 9);
  await api.testDesktopSound("ping");

  expect(sendMessage.mock.calls.map(([message]) => message)).toEqual([
    { type: "api.searches.list" },
    { type: "api.settings.get" },
    {
      type: "api.settings.update",
      payload: { desktop_sound_enabled: false, desktop_sound_id: "ping" },
    },
    { type: "api.listings.recent", limit: 12 },
    { type: "api.templates.list" },
    { type: "api.marketplace.options" },
    { type: "api.search.create", payload: { name: "ThinkPad" } },
    { type: "api.search.update", id: 4, payload: { enabled: false } },
    { type: "api.search.delete", id: 4 },
    { type: "api.template.create", payload: { name: "Kauf", body: "Hallo" } },
    { type: "api.template.update", id: 3, payload: { body: "Servus" } },
    { type: "api.template.delete", id: 3 },
    { type: "api.template.render", templateId: 3, listingId: 9 },
    { type: "api.desktop_sound.test", soundId: "ping" },
  ]);
});
