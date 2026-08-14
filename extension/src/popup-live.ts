import type { ApiService } from "./api-contract";
import type { AgentStatus, Listing } from "./types";

export interface PopupLiveState {
  status: AgentStatus | null;
  latest: Listing | null;
  countdownSeconds: number | null;
  statusError?: unknown;
  listingsError?: unknown;
}

type TimerHandle = number;

export interface PopupLiveTiming {
  wallNow(): number;
  monotonicNow(): number;
  setTimeout(callback: () => void, delay: number): TimerHandle;
  clearTimeout(handle: TimerHandle): void;
}

const UI_TICK_MS = 100;
const CYCLE_POLL_MS = 750;

const defaultTiming: PopupLiveTiming = {
  wallNow: () => Date.now(),
  monotonicNow: () => performance.now(),
  setTimeout: (callback, delay) => window.setTimeout(callback, delay),
  clearTimeout: (handle) => window.clearTimeout(handle),
};

export class PopupLiveController {
  private state: PopupLiveState = {
    status: null,
    latest: null,
    countdownSeconds: null,
  };
  private timer: TimerHandle | null = null;
  private stopped = false;
  private statusRequestRunning = false;
  private lastStatusRequestAt = 0;
  private nextUiTickAt = 0;
  private cycleDisplayStartedAt: number | null = null;
  private cycleDisplaySeconds = 60;
  private confirmedCycleCount = 0;

  constructor(
    private readonly api: ApiService,
    private readonly render: (state: PopupLiveState, now: number) => void,
    private readonly timing: PopupLiveTiming = defaultTiming,
  ) {}

  async start(): Promise<void> {
    await this.refreshStatus(true);
    if (this.stopped) return;
    if (this.state.status) await this.refreshLatest();
    if (this.stopped) return;
    this.renderCurrent();
    this.nextUiTickAt = this.timing.monotonicNow() + UI_TICK_MS;
    this.scheduleNextTick();
  }

  stop(): void {
    this.stopped = true;
    if (this.timer !== null) {
      this.timing.clearTimeout(this.timer);
      this.timer = null;
    }
  }

  async tick(): Promise<void> {
    if (this.stopped) return;
    this.updateVisibleCountdown();
    const now = this.timing.monotonicNow();
    if (this.shouldRefreshStatus(now)) await this.refreshStatus(false);
  }

  private scheduleNextTick(): void {
    if (this.stopped) return;
    const delay = Math.max(0, this.nextUiTickAt - this.timing.monotonicNow());
    this.timer = this.timing.setTimeout(() => {
      this.timer = null;
      void this.tick();
      const now = this.timing.monotonicNow();
      const missedTicks = Math.max(
        1,
        Math.floor((now - this.nextUiTickAt) / UI_TICK_MS) + 1,
      );
      this.nextUiTickAt += missedTicks * UI_TICK_MS;
      this.scheduleNextTick();
    }, delay);
  }

  private shouldRefreshStatus(now: number): boolean {
    if (this.statusRequestRunning) return false;
    const status = this.state.status;
    if (
      status?.scheduler_running &&
      (cycleIsRunning(status) || this.state.countdownSeconds === 0)
    ) {
      return now - this.lastStatusRequestAt >= CYCLE_POLL_MS;
    }
    if (!status || !status.scheduler_running || !status.next_cycle_due_at) {
      return now - this.lastStatusRequestAt >= 30_000;
    }
    return false;
  }

  private async refreshStatus(initial: boolean): Promise<void> {
    if (this.statusRequestRunning || this.stopped) return;
    this.statusRequestRunning = true;
    this.lastStatusRequestAt = this.timing.monotonicNow();
    const previousSuccessfulCycle = this.state.status?.last_successful_willhaben_cycle_at;
    try {
      const status = await this.api.status();
      if (this.stopped) return;
      this.state = { ...this.state, status, statusError: undefined };
      this.synchronizeCycleDisplay(status, initial);
      this.renderCurrent();
      const currentSuccessfulCycle = status.last_successful_willhaben_cycle_at;
      if (
        !initial &&
        currentSuccessfulCycle !== null &&
        currentSuccessfulCycle !== previousSuccessfulCycle
      ) {
        await this.refreshLatest();
      }
    } catch (error) {
      this.state = { ...this.state, statusError: error };
      this.renderCurrent();
    } finally {
      this.statusRequestRunning = false;
    }
  }

  private async refreshLatest(): Promise<void> {
    try {
      const latest = (await this.api.recentListings(1))[0] ?? null;
      if (this.stopped) return;
      this.state = { ...this.state, latest, listingsError: undefined };
    } catch (error) {
      this.state = { ...this.state, listingsError: error };
    }
    this.renderCurrent();
  }

  private renderCurrent(): void {
    if (!this.stopped) this.render(this.state, this.timing.wallNow());
  }

  private synchronizeCycleDisplay(status: AgentStatus, initial: boolean): void {
    const running = cycleIsRunning(status);
    if (initial || this.cycleDisplayStartedAt === null) {
      this.cycleDisplaySeconds = Math.max(1, Math.round(status.cycle_interval_seconds));
      this.confirmedCycleCount = running
        ? Math.max(0, status.total_cycle_count - 1)
        : status.total_cycle_count;
      const dueAt = timestamp(status.next_cycle_due_at);
      const durationMs = this.cycleDisplaySeconds * 1_000;
      const remainingMs =
        dueAt === null
          ? durationMs
          : Math.max(0, Math.min(durationMs, dueAt - this.timing.wallNow()));
      this.cycleDisplayStartedAt =
        this.timing.monotonicNow() - (durationMs - remainingMs);
      this.updateVisibleCountdown(true);
      return;
    }
    if (!running && status.total_cycle_count > this.confirmedCycleCount) {
      this.confirmedCycleCount = status.total_cycle_count;
      this.cycleDisplayStartedAt = this.timing.monotonicNow();
      this.state = { ...this.state, countdownSeconds: this.cycleDisplaySeconds };
    }
  }

  private updateVisibleCountdown(forceRender = false): void {
    if (this.cycleDisplayStartedAt === null) return;
    const elapsedSeconds = Math.floor(
      Math.max(0, this.timing.monotonicNow() - this.cycleDisplayStartedAt) / 1_000,
    );
    const next = Math.max(0, this.cycleDisplaySeconds - elapsedSeconds);
    if (!forceRender && next === this.state.countdownSeconds) return;
    this.state = { ...this.state, countdownSeconds: next };
    this.renderCurrent();
  }
}

function cycleIsRunning(status: AgentStatus): boolean {
  const started = timestamp(status.last_cycle_started_at);
  const completed = timestamp(status.last_cycle_completed_at);
  return started !== null && (completed === null || started > completed);
}

function timestamp(value: string | null): number | null {
  if (!value) return null;
  const parsed = new Date(value).getTime();
  return Number.isNaN(parsed) ? null : parsed;
}
