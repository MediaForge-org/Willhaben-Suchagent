import type { AgentStatus, Listing } from "./types";
import { element, formatPrice, relativeTime } from "./ui";

type ErrorReporter = (context: string, error: unknown) => void;

export function renderOnlinePopup(
  root: HTMLElement,
  status: AgentStatus | null,
  listing: Listing | null,
  endpointErrors: { status?: string; listings?: string } = {},
  reportError: ErrorReporter = reportDevelopmentError,
  now = Date.now(),
  countdownSeconds: number | null = null,
): void {
  root.replaceChildren(createHeading());
  try {
    renderStatus(root, status, endpointErrors.status, now, countdownSeconds);
  } catch (error) {
    reportError("Statusdarstellung fehlgeschlagen", error);
    renderReachableDataError(root, "Statusdaten konnten nicht angezeigt werden.");
  }

  if (listing) {
    try {
      renderListing(root, listing);
    } catch (error) {
      reportError("Listingdarstellung fehlgeschlagen", error);
      root.append(
        element("p", "offline-copy", "Der letzte Fund konnte nicht angezeigt werden."),
      );
    }
  } else if (endpointErrors.listings) {
    root.append(element("p", "offline-copy", "Letzte Inserate konnten nicht geladen werden."));
  }
}

export function renderOfflinePopup(root: HTMLElement): void {
  root.replaceChildren(createHeading());
  const statusLine = element("p", "large-status");
  statusLine.append(
    element("span", "status-dot offline"),
    document.createTextNode("Agent nicht erreichbar"),
  );
  root.append(
    statusLine,
    element("p", "offline-copy", "Der lokale Hintergrunddienst scheint nicht zu laufen."),
  );
}

export function renderNativeHostPopup(root: HTMLElement, message: string): void {
  root.replaceChildren(createHeading());
  const statusLine = element("p", "large-status");
  statusLine.append(
    element("span", "status-dot warning"),
    document.createTextNode("Lokale Verbindung fehlt"),
  );
  root.append(statusLine, element("p", "offline-copy", message));
}

function createHeading(): HTMLElement {
  const heading = element("div", "popup-heading");
  heading.append(
    element("span", "brand-mark small", "W"),
    element("h1", "", "Willhaben-Suchagent"),
  );
  return heading;
}

function renderStatus(
  root: HTMLElement,
  status: AgentStatus | null,
  error: string | undefined,
  now: number,
  countdownSeconds: number | null,
): void {
  if (!status) {
    renderReachableDataError(root, error ?? "Statusdaten konnten nicht geladen werden.");
    return;
  }
  const online = Boolean(status.scheduler_running);
  const statusLine = element("p", "large-status");
  statusLine.append(element("span", `status-dot ${online ? "online" : "warning"}`));
  statusLine.append(
    document.createTextNode(
      online ? "Überwachung aktiv" : "Agent erreichbar, Überwachung pausiert",
    ),
  );
  const timing = element("div", "popup-stats");
  const activeSearches = safeFiniteNumber(status.active_searches, 0);
  timing.append(
    element(
      "strong",
      "",
      `${activeSearches} aktive Suche${activeSearches === 1 ? "" : "n"}`,
    ),
  );
  timing.append(
    element(
      "span",
      "",
      `Letzte Prüfung: ${safeRelativeTime(status.last_cycle_completed_at, now)}`,
    ),
  );
  const nextCycleDueAt = safeDate(status.next_cycle_due_at);
  if (countdownSeconds !== null || nextCycleDueAt) {
    const next =
      countdownSeconds ?? remainingCycleSeconds(nextCycleDueAt!.getTime(), now);
    timing.append(
      element(
        "span",
        "",
        `Nächste Prüfung: in ${next} Sekunde${next === 1 ? "" : "n"}`,
      ),
    );
  }
  root.append(statusLine, timing);
}

export function remainingCycleSeconds(targetTime: number, now: number): number {
  return Math.max(0, Math.ceil((targetTime - now) / 1_000));
}

function renderReachableDataError(root: HTMLElement, message: string): void {
  const statusLine = element("p", "large-status");
  statusLine.append(
    element("span", "status-dot warning"),
    document.createTextNode("Agent erreichbar"),
  );
  root.append(statusLine, element("p", "offline-copy", message));
}

function renderListing(root: HTMLElement, listing: Listing): void {
  const articleLabel = nonEmptyText(listing.article_label, "der Artikel");
  const title = nonEmptyText(listing.title, articleLabel);
  const card = element("section", "popup-listing");
  card.append(
    element("span", "eyebrow", "Letzter Fund"),
    element("h2", "", title),
  );
  card.append(
    element("strong", "price", safePrice(listing.price)),
    element("span", "", nonEmptyText(listing.location, "Ort nicht angegeben")),
  );
  const url = nonEmptyText(listing.url, "");
  if (url) {
    const open = element("button", "button primary full", "Inserat öffnen");
    open.addEventListener("click", () => window.open(url, "_blank", "noopener"));
    card.append(open);
  }
  root.append(card);
}

function nonEmptyText(value: unknown, fallback: string): string {
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function safePrice(value: string | null): string {
  try {
    return formatPrice(value);
  } catch {
    return "Preis nicht angegeben";
  }
}

function safeRelativeTime(value: string | null, now: number): string {
  try {
    return safeDate(value) ? relativeTime(value, now) : "noch nicht";
  } catch {
    return "noch nicht";
  }
}

function safeDate(value: unknown): Date | null {
  if (typeof value !== "string" || !value) return null;
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? null : date;
}

function safeFiniteNumber(value: unknown, fallback: number): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function reportDevelopmentError(context: string, error: unknown): void {
  if (import.meta.env.DEV) console.error(`[Willhaben-Suchagent Popup] ${context}`, error);
}
