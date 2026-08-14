import { expect, test, vi } from "vitest";

import type { ApiService } from "./api-contract";
import {
  PopupLiveController,
  type PopupLiveState,
  type PopupLiveTiming,
} from "./popup-live";
import { renderOnlinePopup } from "./popup-view";
import { listing, settings, status } from "./test-fixtures";

class FakeTiming implements PopupLiveTiming {
  private wallCurrent = new Date("2026-08-13T10:00:00Z").getTime();
  private monotonicCurrent = 0;
  callback: (() => void) | null = null;
  lastDelay = 0;
  clearTimeout = vi.fn(() => {
    this.callback = null;
  });

  get current(): number {
    return this.wallCurrent;
  }

  set current(value: number) {
    this.monotonicCurrent += value - this.wallCurrent;
    this.wallCurrent = value;
  }

  wallNow(): number {
    return this.wallCurrent;
  }

  monotonicNow(): number {
    return this.monotonicCurrent;
  }

  setTimeout(callback: () => void, delay: number): number {
    this.callback = callback;
    this.lastDelay = delay;
    return 7;
  }
}

function liveApi(overrides: Partial<ApiService>): ApiService {
  return {
    status: vi.fn(async () => status),
    settings: vi.fn(async () => settings),
    updateSettings: vi.fn(async () => settings),
    recentListings: vi.fn(async () => [listing]),
    searches: vi.fn(async () => []),
    templates: vi.fn(async () => []),
    marketplaceOptions: vi.fn(async () => ({ categories: [], locations: [] })),
    createSearch: vi.fn(),
    updateSearch: vi.fn(),
    deleteSearch: vi.fn(),
    createTemplate: vi.fn(),
    updateTemplate: vi.fn(),
    deleteTemplate: vi.fn(),
    renderTemplate: vi.fn(),
    testDesktopSound: vi.fn(),
    ...overrides,
  };
}

test("a confirmed cycle renders the complete 60 to 59 to 58 countdown", async () => {
  const root = document.createElement("main");
  const timing = new FakeTiming();
  const controller = new PopupLiveController(
    liveApi({}),
    (state, now) =>
      renderOnlinePopup(
        root,
        state.status,
        state.latest,
        {},
        undefined,
        now,
        state.countdownSeconds,
      ),
    timing,
  );

  await controller.start();
  expect(root.textContent).toContain("Nächste Prüfung: in 60 Sekunden");

  timing.current += 999;
  await controller.tick();
  expect(root.textContent).toContain("Nächste Prüfung: in 60 Sekunden");

  timing.current += 1;
  await controller.tick();
  expect(root.textContent).toContain("Nächste Prüfung: in 59 Sekunden");

  timing.current += 999;
  await controller.tick();
  expect(root.textContent).toContain("Nächste Prüfung: in 59 Sekunden");

  timing.current += 1;
  await controller.tick();
  expect(root.textContent).toContain("Nächste Prüfung: in 58 Sekunden");

  timing.current += 999;
  await controller.tick();
  expect(root.textContent).toContain("Nächste Prüfung: in 58 Sekunden");
});

test("a delayed JavaScript tick corrects itself from the absolute due time", async () => {
  const root = document.createElement("main");
  const timing = new FakeTiming();
  const controller = new PopupLiveController(
    liveApi({}),
    (state, now) =>
      renderOnlinePopup(
        root,
        state.status,
        state.latest,
        {},
        undefined,
        now,
        state.countdownSeconds,
      ),
    timing,
  );
  await controller.start();

  timing.current += 2_250;
  await controller.tick();

  expect(root.textContent).toContain("Nächste Prüfung: in 58 Sekunden");
  expect(root.textContent).not.toContain("in 59 Sekunden");
});

test("the local timer realigns to its 100 ms grid after a late callback", async () => {
  const timing = new FakeTiming();
  const controller = new PopupLiveController(liveApi({}), vi.fn(), timing);
  await controller.start();
  const lateCallback = timing.callback;

  timing.current += 690;
  lateCallback?.();

  expect(timing.lastDelay).toBe(10);
});

test("8 to 7 uses the same one-second monotonic boundary without cumulative drift", async () => {
  const root = document.createElement("main");
  const timing = new FakeTiming();
  const controller = new PopupLiveController(
    liveApi({}),
    (state, now) =>
      renderOnlinePopup(
        root,
        state.status,
        state.latest,
        {},
        undefined,
        now,
        state.countdownSeconds,
      ),
    timing,
  );
  await controller.start();

  timing.current += 52_000;
  await controller.tick();
  expect(root.textContent).toContain("Nächste Prüfung: in 8 Sekunden");

  timing.current += 999;
  await controller.tick();
  expect(root.textContent).toContain("Nächste Prüfung: in 8 Sekunden");

  timing.current += 1;
  await controller.tick();
  expect(root.textContent).toContain("Nächste Prüfung: in 7 Sekunden");
});

test("status is not reloaded or re-anchored inside the visible cycle", async () => {
  const timing = new FakeTiming();
  const statusRequest = vi.fn(async () => status);
  const rendered: PopupLiveState[] = [];
  const controller = new PopupLiveController(
    liveApi({ status: statusRequest }),
    (state) => rendered.push({ ...state }),
    timing,
  );
  await controller.start();

  timing.current += 12_345;
  await controller.tick();
  timing.current += 7_655;
  await controller.tick();

  expect(statusRequest).toHaveBeenCalledOnce();
  expect(rendered.at(-1)?.countdownSeconds).toBe(40);
});

test("the expected due time is polled until completion then resets to 60", async () => {
  const root = document.createElement("main");
  const timing = new FakeTiming();
  const runningStatus = {
    ...status,
    total_cycle_count: 5,
    last_cycle_started_at: "2026-08-13T10:01:00Z",
    last_cycle_completed_at: "2026-08-13T10:00:01Z",
  };
  const completedStatus = {
    ...runningStatus,
    next_cycle_due_at: "2026-08-13T10:02:00.750Z",
    last_cycle_completed_at: "2026-08-13T10:01:00.750Z",
    last_successful_willhaben_cycle_at: "2026-08-13T10:01:00.750Z",
  };
  const newest = { ...listing, listing_id: 10, title: "Sony WH-1000XM5" };
  const statusRequest = vi
    .fn()
    .mockResolvedValueOnce(status)
    .mockResolvedValueOnce(runningStatus)
    .mockResolvedValueOnce(completedStatus);
  const listingsRequest = vi
    .fn()
    .mockResolvedValueOnce([listing])
    .mockResolvedValueOnce([newest]);
  const api = liveApi({ status: statusRequest, recentListings: listingsRequest });
  const controller = new PopupLiveController(
    api,
    (state, now) =>
      renderOnlinePopup(
        root,
        state.status,
        state.latest,
        {},
        undefined,
        now,
        state.countdownSeconds,
      ),
    timing,
  );
  await controller.start();

  timing.current = new Date("2026-08-13T10:01:00Z").getTime();
  await controller.tick();
  expect(root.textContent).toContain("Nächste Prüfung: in 0 Sekunden");

  timing.current += 750;
  await controller.tick();
  expect(root.textContent).toContain("Letzte Prüfung: gerade eben");
  expect(root.textContent).toContain("Nächste Prüfung: in 60 Sekunden");
  expect(root.textContent).toContain("Sony WH-1000XM5");
  expect(statusRequest).toHaveBeenCalledTimes(3);
  expect(listingsRequest).toHaveBeenCalledTimes(2);
  expect(api.searches).not.toHaveBeenCalled();
  expect(api.templates).not.toHaveBeenCalled();
  expect(api.marketplaceOptions).not.toHaveBeenCalled();
});

test("zero remains visible through same-cycle responses until completion is confirmed", async () => {
  const root = document.createElement("main");
  const timing = new FakeTiming();
  const sameCycle = { ...status, next_cycle_due_at: "2026-08-13T10:01:00Z" };
  const statusRequest = vi
    .fn()
    .mockResolvedValueOnce(status)
    .mockResolvedValueOnce(sameCycle)
    .mockResolvedValueOnce(sameCycle);
  const controller = new PopupLiveController(
    liveApi({ status: statusRequest }),
    (state, now) =>
      renderOnlinePopup(
        root,
        state.status,
        state.latest,
        {},
        undefined,
        now,
        state.countdownSeconds,
      ),
    timing,
  );
  await controller.start();

  timing.current += 60_000;
  await controller.tick();
  timing.current += 750;
  await controller.tick();

  expect(statusRequest).toHaveBeenCalledTimes(3);
  expect(root.textContent).toContain("Nächste Prüfung: in 0 Sekunden");
});

test("status polling never refreshes listings without a newly successful cycle", async () => {
  const timing = new FakeTiming();
  const statusRequest = vi.fn(async () => status);
  const listingsRequest = vi.fn(async () => [listing]);
  const controller = new PopupLiveController(
    liveApi({ status: statusRequest, recentListings: listingsRequest }),
    vi.fn(),
    timing,
  );
  await controller.start();

  timing.current = new Date("2026-08-13T10:01:00Z").getTime();
  await controller.tick();

  expect(statusRequest).toHaveBeenCalledTimes(2);
  expect(listingsRequest).toHaveBeenCalledOnce();
});

test("closing the popup clears its self-correcting timer and stops polling", async () => {
  const timing = new FakeTiming();
  const statusRequest = vi.fn(async () => status);
  const controller = new PopupLiveController(
    liveApi({ status: statusRequest }),
    vi.fn(),
    timing,
  );
  await controller.start();

  expect(timing.lastDelay).toBe(100);
  controller.stop();
  timing.current += 120_000;
  await controller.tick();

  expect(timing.clearTimeout).toHaveBeenCalledExactlyOnceWith(7);
  expect(statusRequest).toHaveBeenCalledOnce();
});
