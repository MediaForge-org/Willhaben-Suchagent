import { expect, test, vi } from "vitest";

import {
  ApiDataError,
  ApiHttpError,
  ApiNativeHostError,
  ApiTransportError,
} from "./api-contract";
import type {
  ApiBrokerResponse,
  NativeRequestEnvelope,
  NativeResponseEnvelope,
} from "./broker-protocol";
import {
  NativeApiClient,
  NATIVE_HOST_NAME,
  type NativeConnector,
  type NativePort,
} from "./native-api";

class FakeEvent<Argument> {
  private listeners = new Set<(argument: Argument) => void>();

  addListener(listener: (argument: Argument) => void): void {
    this.listeners.add(listener);
  }

  removeListener(listener: (argument: Argument) => void): void {
    this.listeners.delete(listener);
  }

  emit(argument: Argument): void {
    for (const listener of this.listeners) listener(argument);
  }
}

class FakeNativePort implements NativePort {
  error?: Error;
  readonly messages: NativeRequestEnvelope[] = [];
  readonly onMessage = new FakeEvent<unknown>();
  readonly onDisconnect = new FakeEvent<NativePort>();
  disconnect = vi.fn(() => this.onDisconnect.emit(this));

  postMessage(message: NativeRequestEnvelope): void {
    this.messages.push(message);
  }

  respond(index: number, response: ApiBrokerResponse): void {
    const requestId = this.messages[index]?.requestId;
    if (!requestId) throw new Error("Missing test request");
    const envelope: NativeResponseEnvelope = { requestId, response };
    this.onMessage.emit(envelope);
  }

  fail(error: Error): void {
    this.error = error;
    this.onDisconnect.emit(this);
  }
}

function connector(...ports: FakeNativePort[]): NativeConnector & {
  connectNative: ReturnType<typeof vi.fn>;
} {
  let index = 0;
  return {
    connectNative: vi.fn(() => ports[index++] ?? ports.at(-1)!),
  };
}

test("background status request uses connectNative and the fixed host", async () => {
  const port = new FakeNativePort();
  const runtime = connector(port);
  const api = new NativeApiClient(runtime);

  const pending = api.status();
  port.respond(0, { ok: true, data: { scheduler_running: true } });

  await expect(pending).resolves.toMatchObject({ scheduler_running: true });
  expect(runtime.connectNative).toHaveBeenCalledExactlyOnceWith(NATIVE_HOST_NAME);
  expect(port.messages[0]?.request).toEqual({ type: "api.status" });
});

test("multiple requests share one persistent native port", async () => {
  const port = new FakeNativePort();
  const runtime = connector(port);
  const api = new NativeApiClient(runtime);

  const first = api.status();
  const second = api.status();
  const third = api.recentListings(1);
  port.respond(0, { ok: true, data: { cycle: 1 } });
  port.respond(1, { ok: true, data: { cycle: 2 } });
  port.respond(2, { ok: true, data: [] });

  await Promise.all([first, second, third]);
  expect(runtime.connectNative).toHaveBeenCalledOnce();
  expect(new Set(port.messages.map(({ requestId }) => requestId)).size).toBe(3);
});

test("request IDs associate out-of-order native responses correctly", async () => {
  const port = new FakeNativePort();
  const api = new NativeApiClient(connector(port));

  const status = api.status();
  const listings = api.recentListings(1);
  port.respond(1, { ok: true, data: [{ listing_id: 9 }] });
  port.respond(0, { ok: true, data: { total_cycle_count: 4 } });

  await expect(status).resolves.toMatchObject({ total_cycle_count: 4 });
  await expect(listings).resolves.toEqual([{ listing_id: 9 }]);
});

test("disconnect rejects pending work and the next request reconnects once", async () => {
  const firstPort = new FakeNativePort();
  const secondPort = new FakeNativePort();
  const runtime = connector(firstPort, secondPort);
  const api = new NativeApiClient(runtime);

  const disconnected = api.status();
  firstPort.fail(new Error("Native host exited"));
  await expect(disconnected).rejects.toMatchObject({ reason: "not_startable" });

  const reconnected = api.status();
  secondPort.respond(0, { ok: true, data: { scheduler_running: true } });
  await expect(reconnected).resolves.toMatchObject({ scheduler_running: true });
  expect(runtime.connectNative).toHaveBeenCalledTimes(2);
});

test("native client distinguishes missing host, agent, HTTP and data failures", async () => {
  const missingPort = new FakeNativePort();
  const errorPort = new FakeNativePort();
  const runtime = connector(missingPort, errorPort);
  const api = new NativeApiClient(runtime);

  const missing = api.status();
  missingPort.fail(new Error("No such native application"));
  await expect(missing).rejects.toMatchObject({
    reason: "not_installed",
  } satisfies Partial<ApiNativeHostError>);

  const transport = api.status();
  errorPort.respond(0, { ok: false, error: { kind: "transport", message: "offline" } });
  await expect(transport).rejects.toBeInstanceOf(ApiTransportError);

  const http = api.status();
  errorPort.respond(1, {
    ok: false,
    error: { kind: "http", message: "failed", status: 503 },
  });
  await expect(http).rejects.toBeInstanceOf(ApiHttpError);

  const invalid = api.status();
  errorPort.onMessage.emit({ invalid: true });
  await expect(invalid).rejects.toBeInstanceOf(ApiDataError);
});

test("all background capabilities keep fixed broker operations", async () => {
  const port = new FakeNativePort();
  const api = new NativeApiClient(connector(port));
  const calls = [
    api.searches(),
    api.settings(),
    api.updateSettings({ desktop_sound_enabled: false, desktop_sound_id: "ping" }),
    api.templates(),
    api.marketplaceOptions(),
    api.createSearch({ name: "ThinkPad" }),
    api.updateSearch(4, { enabled: false }),
    api.deleteSearch(4),
    api.createTemplate({ name: "Kauf", body: "Hallo" }),
    api.updateTemplate(3, { body: "Servus" }),
    api.deleteTemplate(3),
    api.renderTemplate(3, 9),
    api.testDesktopSound("ping"),
  ];
  for (let index = 0; index < calls.length; index += 1) {
    port.respond(index, { ok: true, data: null });
  }

  await Promise.all(calls);
  expect(port.messages.map(({ request }) => request.type)).toEqual([
    "api.searches.list",
    "api.settings.get",
    "api.settings.update",
    "api.templates.list",
    "api.marketplace.options",
    "api.search.create",
    "api.search.update",
    "api.search.delete",
    "api.template.create",
    "api.template.update",
    "api.template.delete",
    "api.template.render",
    "api.desktop_sound.test",
  ]);
});
