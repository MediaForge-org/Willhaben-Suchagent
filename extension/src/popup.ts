import { ApiClient } from "./api";
import { element, formatPrice, relativeTime } from "./ui";

const api = new ApiClient();
const root = document.querySelector<HTMLElement>("#popup")!;

function dashboardUrl(): string {
  return typeof browser !== "undefined" ? browser.runtime.getURL("dashboard.html") : "dashboard.html";
}

async function renderPopup(): Promise<void> {
  root.replaceChildren();
  try {
    const [status, listings] = await Promise.all([api.status(), api.recentListings(1)]);
    const heading = element("div", "popup-heading");
    heading.append(element("span", "brand-mark small", "W"), element("h1", "", "Willhaben-Suchagent"));
    const online = status.scheduler_running;
    const statusLine = element("p", "large-status");
    statusLine.append(element("span", `status-dot ${online ? "online" : "warning"}`));
    statusLine.append(document.createTextNode(online ? "Überwachung aktiv" : "Agent erreichbar, Überwachung pausiert"));
    root.append(heading, statusLine);

    const timing = element("div", "popup-stats");
    timing.append(element("strong", "", `${status.active_searches} aktive Suche${status.active_searches === 1 ? "" : "n"}`));
    timing.append(element("span", "", `Letzte Prüfung: ${relativeTime(status.last_cycle_completed_at)}`));
    if (status.last_cycle_started_at) {
      const next = Math.max(0, Math.round(status.cycle_interval_seconds - (Date.now() - new Date(status.last_cycle_started_at).getTime()) / 1000));
      timing.append(element("span", "", `Nächste Prüfung: in ${next} Sekunden`));
    }
    root.append(timing);

    const latest = listings[0];
    if (latest) {
      const card = element("section", "popup-listing");
      card.append(element("span", "eyebrow", "Letzter Fund"), element("h2", "", latest.article_label));
      if (latest.title !== latest.article_label) card.append(element("p", "subtle clamp", latest.title));
      card.append(element("strong", "price", formatPrice(latest.price)), element("span", "", latest.location ?? "Ort nicht angegeben"));
      const open = element("button", "button primary full", "Inserat öffnen");
      open.addEventListener("click", () => window.open(latest.url, "_blank", "noopener"));
      card.append(open);
      root.append(card);
    }
  } catch {
    const heading = element("div", "popup-heading");
    heading.append(element("span", "brand-mark small", "W"), element("h1", "", "Willhaben-Suchagent"));
    const statusLine = element("p", "large-status");
    statusLine.append(element("span", "status-dot offline"), document.createTextNode("Agent nicht erreichbar"));
    root.append(heading, statusLine, element("p", "offline-copy", "Der lokale Hintergrunddienst scheint nicht zu laufen."));
  }
  const dashboard = element("button", "button secondary full", "Dashboard öffnen");
  dashboard.addEventListener("click", () => window.open(dashboardUrl(), "_blank", "noopener"));
  root.append(dashboard);
}

void renderPopup();
window.setInterval(() => void renderPopup(), 30_000);
