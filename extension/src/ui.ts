import type { Listing, MessageTemplate, Search } from "./types";

export function element<K extends keyof HTMLElementTagNameMap>(
  tag: K,
  className?: string,
  text?: string,
): HTMLElementTagNameMap[K] {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
}

export function formatPrice(value: string | null): string {
  if (value === null) return "Preis nicht angegeben";
  return `${new Intl.NumberFormat("de-AT", { maximumFractionDigits: 2 }).format(Number(value))} €`;
}

export function relativeTime(value: string | null): string {
  if (!value) return "noch nicht";
  const seconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000));
  if (seconds < 60) return `vor ${seconds} Sekunde${seconds === 1 ? "" : "n"}`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 60) return `vor ${minutes} Minute${minutes === 1 ? "" : "n"}`;
  return new Intl.DateTimeFormat("de-AT", { dateStyle: "medium", timeStyle: "short" }).format(new Date(value));
}

export function renderSearchList(searches: Search[]): HTMLElement {
  const list = element("div", "card-grid search-grid");
  if (!searches.length) {
    list.append(element("p", "empty-state", "Noch keine Suche angelegt."));
    return list;
  }
  for (const search of searches) {
    const card = element("article", "card search-card");
    card.dataset.searchId = String(search.id);
    const top = element("div", "card-top");
    top.append(element("h3", "", search.name));
    top.append(element("span", `badge ${search.enabled ? "success" : "muted"}`, search.enabled ? "Live: EIN" : "Live: AUS"));
    const range = [search.price_min, search.price_max].filter(Boolean).join("–");
    const meta = element("p", "meta", `Marketplace · ${search.query || "Alle Inserate"}`);
    const details = element("p", "subtle", [range ? `${range} €` : null, search.location].filter(Boolean).join(" · ") || "Keine weiteren Filter");
    const health = element(
      "p",
      search.consecutive_errors ? "status-text error" : "status-text",
      search.consecutive_errors
        ? "Letzte Prüfung fehlgeschlagen"
        : search.baseline_initialized
          ? `Bereit · zuletzt erfolgreich ${relativeTime(search.last_success_at)}`
          : "Baseline wird bei der nächsten Prüfung erstellt",
    );
    const actions = element("div", "actions");
    for (const [action, label, style] of [
      ["edit", "Bearbeiten", "secondary"],
      ["toggle", search.enabled ? "Deaktivieren" : "Aktivieren", "secondary"],
      ["delete", "Löschen", "danger-text"],
    ] as const) {
      const button = element("button", `button ${style}`, label);
      button.dataset.action = action;
      actions.append(button);
    }
    card.append(top, meta, details, health, actions);
    list.append(card);
  }
  return list;
}

export function renderTemplateList(templates: MessageTemplate[]): HTMLElement {
  const list = element("div", "card-grid template-grid");
  if (!templates.length) {
    list.append(element("p", "empty-state", "Noch kein Template vorhanden."));
    return list;
  }
  for (const template of templates) {
    const card = element("article", "card template-card");
    card.dataset.templateId = String(template.id);
    card.append(element("h3", "", template.name));
    const preview = element("pre", "template-preview", template.body);
    const actions = element("div", "actions");
    for (const [action, label, style] of [
      ["edit", "Bearbeiten", "secondary"],
      ["duplicate", "Duplizieren", "secondary"],
      ["delete", "Löschen", "danger-text"],
    ] as const) {
      const button = element("button", `button ${style}`, label);
      button.dataset.action = action;
      actions.append(button);
    }
    card.append(preview, actions);
    list.append(card);
  }
  return list;
}

export interface TextClipboard {
  writeText(text: string): Promise<void>;
}

export async function copyPreparedMessage(
  text: string,
  clipboard: TextClipboard = navigator.clipboard,
): Promise<void> {
  await clipboard.writeText(text);
}

export function chooseDefaultTemplate(
  listing: Listing,
  searches: Search[],
  templates: MessageTemplate[],
): number | null {
  for (const searchId of listing.search_ids) {
    const templateId = searches.find((search) => search.id === searchId)?.default_template_id;
    if (templateId && templates.some((template) => template.id === templateId)) return templateId;
  }
  return templates[0]?.id ?? null;
}
