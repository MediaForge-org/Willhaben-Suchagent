import { isApiNativeHostError, isApiTransportError } from "./api-contract";
import { PopupLiveController, type PopupLiveState } from "./popup-live";
import {
  renderNativeHostPopup,
  renderOfflinePopup,
  renderOnlinePopup,
} from "./popup-view";
import { RuntimeApiClient } from "./runtime-api";
import { element } from "./ui";

const api = new RuntimeApiClient();
const root = document.querySelector<HTMLElement>("#popup")!;

function dashboardUrl(): string {
  return typeof browser !== "undefined"
    ? browser.runtime.getURL("dashboard.html")
    : "dashboard.html";
}

function renderPopupState(state: PopupLiveState, now: number): void {
  if (!state.status && isApiNativeHostError(state.statusError)) {
    renderNativeHostPopup(root, state.statusError.message);
  } else if (!state.status && isApiTransportError(state.statusError)) {
    renderOfflinePopup(root);
  } else {
    renderOnlinePopup(
      root,
      state.status,
      state.latest,
      {
        status: errorMessage(state.statusError),
        listings: errorMessage(state.listingsError),
      },
      undefined,
      now,
      state.countdownSeconds,
    );
  }
  appendDashboardButton();
}

function errorMessage(error: unknown): string | undefined {
  return error instanceof Error ? error.message : undefined;
}

function appendDashboardButton(): void {
  const dashboard = element("button", "button secondary full", "Dashboard öffnen");
  dashboard.addEventListener("click", () =>
    window.open(dashboardUrl(), "_blank", "noopener"),
  );
  root.append(dashboard);
}

const live = new PopupLiveController(api, renderPopupState);
window.addEventListener("pagehide", () => live.stop(), { once: true });
window.addEventListener("unload", () => live.stop(), { once: true });
void live.start();
