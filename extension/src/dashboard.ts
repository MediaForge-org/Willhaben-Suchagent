import { RuntimeApiClient } from "./runtime-api";
import { loadAgentSnapshot } from "./state";
import type { AgentSnapshot, Listing, MessageTemplate, Search } from "./types";
import {
  copyPreparedMessage,
  chooseDefaultTemplate,
  element,
  formatPrice,
  previewDesktopSound,
  relativeTime,
  renderSearchList,
  renderTemplateList,
} from "./ui";

const api = new RuntimeApiClient();
const content = document.querySelector<HTMLElement>("#content")!;
const banner = document.querySelector<HTMLElement>("#connection-banner")!;
const modalRoot = document.querySelector<HTMLElement>("#modal-root")!;
let snapshot: AgentSnapshot | null = null;
let connectionFailure:
  | { reason: "agent_unreachable" | "native_host_missing" | "native_host_start"; message: string }
  | null = null;

type View = "overview" | "searches" | "listings" | "templates" | "settings";

function currentView(): View {
  const value = location.hash.slice(1);
  return ["overview", "searches", "listings", "templates", "settings"].includes(value)
    ? (value as View)
    : "overview";
}

function pageHeader(title: string, description: string, action?: HTMLElement): HTMLElement {
  const wrapper = element("header", "page-header");
  const copy = element("div");
  copy.append(element("h1", "", title), element("p", "", description));
  wrapper.append(copy);
  if (action) wrapper.append(action);
  return wrapper;
}

function activateNavigation(view: View): void {
  document.querySelectorAll<HTMLAnchorElement>("#navigation a").forEach((link) => {
    const active = link.dataset.view === view;
    link.classList.toggle("active", active);
    if (active) link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
}

async function refresh(showLoading = true): Promise<void> {
  if (showLoading) content.replaceChildren(element("div", "loading", "Daten werden geladen …"));
  const connection = await loadAgentSnapshot(api);
  if (!connection.online) {
    connectionFailure = connection;
    banner.hidden = false;
    banner.textContent = snapshot
      ? `${connection.message} Die zuletzt geladenen Daten bleiben sichtbar; neuer Versuch in 30 Sekunden.`
      : `${connection.message} Neuer Versuch in 30 Sekunden.`;
  } else {
    connectionFailure = null;
    snapshot = connection.data;
    const failedEndpoints = Object.keys(snapshot.endpointErrors);
    banner.hidden = failedEndpoints.length === 0;
    if (failedEndpoints.length) {
      banner.textContent =
        "Agent erreichbar. Einzelne Bereiche konnten nicht geladen werden; neuer Versuch in 30 Sekunden.";
    }
  }
  renderView();
}

function renderView(): void {
  const view = currentView();
  activateNavigation(view);
  if (!snapshot) {
    const retry = element("button", "button primary", "Erneut versuchen");
    retry.addEventListener("click", () => void refresh());
    const offline = element("section", "offline-panel");
    const nativeHostMissing = connectionFailure?.reason === "native_host_missing";
    const nativeHostStart = connectionFailure?.reason === "native_host_start";
    offline.append(
      element("div", "offline-icon", "!"),
      element(
        "h1",
        "",
        nativeHostMissing || nativeHostStart
          ? "Lokale Verbindung fehlt"
          : "Agent nicht erreichbar",
      ),
      element(
        "p",
        "",
        connectionFailure?.message ??
          "Der lokale Hintergrunddienst scheint nicht zu laufen.",
      ),
      retry,
    );
    content.replaceChildren(offline);
    return;
  }
  const renderers: Record<View, () => void> = {
    overview: renderOverview,
    searches: renderSearches,
    listings: renderListings,
    templates: renderTemplates,
    settings: renderSettings,
  };
  renderers[view]();
  content.focus({ preventScroll: true });
}

function renderOverview(): void {
  const data = snapshot!;
  const fragment = document.createDocumentFragment();
  fragment.append(pageHeader("Guten Tag", "Hier siehst du, was dein Suchagent gerade macht."));
  const stats = element("div", "stats-grid");
  const values = [
    [data.status ? String(data.status.active_searches) : "–", "Aktive Suchen"],
    [data.status ? (data.status.scheduler_running ? "Aktiv" : "Pausiert") : "Unbekannt", "Überwachung"],
    [data.status ? relativeTime(data.status.last_cycle_completed_at) : "nicht verfügbar", "Letzte Prüfung"],
    [String(data.listings.length), "Letzte Inserate"],
  ];
  for (const [value, label] of values) {
    const card = element("article", "stat-card");
    card.append(element("strong", "", value), element("span", "", label));
    stats.append(card);
  }
  fragment.append(stats);
  const recent = element("section", "section-block");
  const titleRow = element("div", "section-heading");
  titleRow.append(element("h2", "", "Zuletzt gefunden"));
  const all = element("a", "text-link", "Alle Inserate ansehen");
  all.href = "#listings";
  titleRow.append(all);
  recent.append(titleRow);
  const latest = data.listings.slice(0, 3);
  recent.append(latest.length ? listingGrid(latest, false) : element("p", "empty-state", "Noch keine Inserate gefunden."));
  fragment.append(recent);
  content.replaceChildren(fragment);
}

function renderSearches(): void {
  const add = element("button", "button primary", "+ Neue Suche");
  add.addEventListener("click", () => openSearchEditor());
  const list = renderSearchList(snapshot!.searches);
  list.addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>("button[data-action]");
    const card = button?.closest<HTMLElement>("[data-search-id]");
    if (!button || !card) return;
    const search = snapshot!.searches.find((item) => item.id === Number(card.dataset.searchId));
    if (!search) return;
    if (button.dataset.action === "edit") openSearchEditor(search);
    if (button.dataset.action === "toggle") void mutate(() => api.updateSearch(search.id, { enabled: !search.enabled }));
    if (button.dataset.action === "delete" && confirm(`„${search.name}“ wirklich löschen?`)) {
      void mutate(() => api.deleteSearch(search.id));
    }
  });
  content.replaceChildren(
    pageHeader("Meine Suchen", "Verwalte deine Live-Suchen auf dem Willhaben-Marktplatz.", add),
    list,
  );
}

function renderListings(): void {
  content.replaceChildren(
    pageHeader("Neue Inserate", "Die zuletzt vom Agenten gefundenen Marketplace-Inserate."),
    snapshot!.listings.length
      ? listingGrid(snapshot!.listings, true)
      : element("p", "empty-state", "Noch keine Inserate gefunden."),
  );
}

function listingGrid(listings: Listing[], allowMessage: boolean): HTMLElement {
  const grid = element("div", "listing-grid");
  for (const listing of listings) {
    const card = element("article", "listing-card");
    if (listing.image_url) {
      const image = element("img", "listing-image");
      image.src = listing.image_url;
      image.alt = "";
      image.loading = "lazy";
      card.append(image);
    } else {
      card.append(element("div", "listing-image placeholder", "Kein Bild"));
    }
    const body = element("div", "listing-body");
    body.append(element("h3", "", listing.title));
    body.append(element("strong", "price", formatPrice(listing.price)));
    const sellerLabel = listing.seller_type === "commercial" ? "Anbieter" : "Verkäufer";
    body.append(
      element("p", "meta", listing.seller_name ? `${sellerLabel}: ${listing.seller_name}` : "Verkäufer nicht angegeben"),
      element("p", "meta", [listing.location, listing.condition].filter(Boolean).join(" · ") || "Keine weiteren Angaben"),
      element("p", "subtle", `${listing.search_names.join(", ") || "Suche nicht mehr vorhanden"} · ${relativeTime(listing.first_seen_at)}`),
    );
    const actions = element("div", "actions");
    const open = element("button", "button secondary", "Inserat öffnen");
    open.addEventListener("click", () => window.open(listing.url, "_blank", "noopener"));
    actions.append(open);
    if (allowMessage) {
      const prepare = element("button", "button primary", "Nachricht vorbereiten");
      prepare.addEventListener("click", () => openMessageDialog(listing));
      actions.append(prepare);
    }
    body.append(actions);
    card.append(body);
    grid.append(card);
  }
  return grid;
}

function renderTemplates(): void {
  const add = element("button", "button primary", "+ Neues Template");
  add.addEventListener("click", () => openTemplateEditor());
  const list = renderTemplateList(snapshot!.templates);
  list.addEventListener("click", (event) => {
    const button = (event.target as HTMLElement).closest<HTMLButtonElement>("button[data-action]");
    const card = button?.closest<HTMLElement>("[data-template-id]");
    if (!button || !card) return;
    const template = snapshot!.templates.find((item) => item.id === Number(card.dataset.templateId));
    if (!template) return;
    if (button.dataset.action === "edit") openTemplateEditor(template);
    if (button.dataset.action === "duplicate") openTemplateEditor(undefined, { name: `${template.name} (Kopie)`, body: template.body });
    if (button.dataset.action === "delete" && confirm(`Template „${template.name}“ wirklich löschen? Zugeordnete Suchen verwenden danach kein Standard-Template mehr.`)) {
      void mutate(() => api.deleteTemplate(template.id));
    }
  });
  content.replaceChildren(
    pageHeader("Templates", "Bereite persönliche Nachrichten vor, ohne sie automatisch zu versenden.", add),
    list,
  );
}

function renderSettings(): void {
  const safety = element("section", "card settings-card");
  const soundStatus = snapshot!.status;
  const soundSettings = snapshot!.settings;
  safety.append(
    element("h2", "", "Lokaler Agent"),
    element("p", "", "Verbindung über Firefox Native Messaging"),
    element("code", "api-address", "at.willhaben_suchagent.bridge"),
    element("p", "subtle", "Die Extension spricht ausschließlich mit der installierten lokalen Bridge. Sie benötigt weder Willhaben-Login noch Cookies oder Passwörter."),
    element("h2", "", "Desktop-Sound"),
  );
  if (!soundSettings) {
    safety.append(
      element("p", "subtle", "Soundeinstellungen sind derzeit nicht verfügbar."),
    );
  } else {
    const controls = element("div", "sound-settings");
    const enabled = input("desktop_sound_enabled", "", "checkbox");
    enabled.checked = soundSettings.desktop_sound_enabled;
    const enabledLabel = field("Sound EIN/AUS", enabled);
    const badge = element(
      "span",
      `badge ${enabled.checked ? "success" : "muted"}`,
      enabled.checked ? "EIN" : "AUS",
    );
    enabledLabel.append(badge);
    const soundSelect = select(
      "desktop_sound_id",
      soundSettings.desktop_sounds.map((sound) => ({
        label: sound.name,
        value: sound.id,
      })),
      soundSettings.desktop_sound_id,
    );
    const testSound = element("button", "button secondary", "Ton testen");
    testSound.type = "button";
    const result = element("p", "subtle");
    const persist = async (payload: {
      desktop_sound_enabled?: boolean;
      desktop_sound_id?: string;
    }) => {
      enabled.disabled = true;
      soundSelect.disabled = true;
      testSound.disabled = true;
      result.textContent = "Einstellung wird gespeichert …";
      try {
        snapshot!.settings = await api.updateSettings(payload);
        if (snapshot!.status) {
          snapshot!.status.desktop_sound_enabled =
            snapshot!.settings.desktop_sound_enabled;
          snapshot!.status.desktop_sound_id = snapshot!.settings.desktop_sound_id;
        }
        renderSettings();
      } catch (error) {
        enabled.checked = snapshot!.settings!.desktop_sound_enabled;
        soundSelect.value = snapshot!.settings!.desktop_sound_id;
        result.textContent =
          error instanceof Error ? error.message : "Einstellung konnte nicht gespeichert werden.";
        enabled.disabled = false;
        soundSelect.disabled = false;
        testSound.disabled = false;
      }
    };
    enabled.addEventListener("change", () => {
      void persist({ desktop_sound_enabled: enabled.checked });
    });
    soundSelect.addEventListener("change", () => {
      void persist({ desktop_sound_id: soundSelect.value });
    });
    testSound.addEventListener("click", async () => {
      testSound.disabled = true;
      result.textContent = "Sound wird abgespielt …";
      try {
        const response = await previewDesktopSound(api, soundSelect.value);
        result.textContent = response.message;
      } catch (error) {
        result.textContent =
          error instanceof Error ? error.message : "Soundtest ist fehlgeschlagen.";
      } finally {
        testSound.disabled = false;
      }
    });
    controls.append(
      enabledLabel,
      field("Benachrichtigungston", soundSelect),
      testSound,
      result,
    );
    safety.append(
      controls,
      element(
        "p",
        "subtle",
        !soundSettings.desktop_sound_enabled
          ? "Desktop-Sound ist ausgeschaltet; Ton testen bleibt als manuelle Vorschau möglich."
          : soundStatus?.desktop_sound_available
            ? "Bei neuen Inseraten spielt der Agent maximal einmal pro Cycle den gewählten Ton."
            : soundStatus?.desktop_sound_disabled_reason ??
                "Die Audio-Ausgabe ist derzeit nicht verfügbar.",
      ),
    );
  }
  safety.append(
    element("h2", "", "Nachrichten bleiben manuell"),
    element("p", "", "Die Extension rendert Text im Agenten, kopiert ihn auf Wunsch und öffnet das Inserat. Sie füllt kein Willhaben-Formular aus und klickt niemals auf Senden."),
  );
  content.replaceChildren(pageHeader("Einstellungen", "Verbindung und Sicherheitsprinzipien."), safety);
}

function modal(title: string): { dialog: HTMLElement; body: HTMLElement; close: () => void } {
  const backdrop = element("div", "modal-backdrop");
  const dialog = element("section", "modal");
  dialog.setAttribute("role", "dialog");
  dialog.setAttribute("aria-modal", "true");
  const header = element("header", "modal-header");
  header.append(element("h2", "", title));
  const closeButton = element("button", "icon-button", "×");
  closeButton.setAttribute("aria-label", "Schließen");
  const close = () => modalRoot.replaceChildren();
  closeButton.addEventListener("click", close);
  header.append(closeButton);
  const body = element("div", "modal-body");
  dialog.append(header, body);
  backdrop.append(dialog);
  backdrop.addEventListener("click", (event) => { if (event.target === backdrop) close(); });
  modalRoot.replaceChildren(backdrop);
  closeButton.focus();
  return { dialog, body, close };
}

function field(labelText: string, input: HTMLElement): HTMLElement {
  const label = element("label", "field");
  label.append(element("span", "", labelText), input);
  return label;
}

function input(name: string, value = "", type = "text"): HTMLInputElement {
  const node = element("input");
  node.name = name;
  node.type = type;
  node.value = value;
  return node;
}

function select(name: string, options: Array<{ label: string; value: string }>, value = ""): HTMLSelectElement {
  const node = element("select");
  node.name = name;
  for (const option of options) {
    const item = element("option", "", option.label);
    item.value = option.value;
    item.selected = option.value === value;
    node.append(item);
  }
  return node;
}

function openSearchEditor(search?: Search): void {
  const { body, close } = modal(search ? "Suche bearbeiten" : "Neue Marketplace-Suche");
  const form = element("form", "form-grid");
  const categoryValue = String(search?.category_filters.marketplace_category ?? "");
  const categoryOptions = [{ label: "Alle unterstützten Marketplace-Kategorien", value: "" }, ...snapshot!.options.categories];
  const locationOptions = [{ label: "Ganz Österreich", value: "" }, ...snapshot!.options.locations];
  const templateOptions = [
    { label: "Kein Standard-Template", value: "" },
    ...snapshot!.templates.map((template) => ({ label: template.name, value: String(template.id) })),
  ];
  const enabled = input("enabled", "", "checkbox");
  enabled.checked = search?.enabled ?? true;
  form.append(
    field("Name der Suche", input("name", search?.name ?? "")),
    field("Suchbegriff", input("query", search?.query ?? "")),
    field("Preis von (€)", input("price_min", search?.price_min ?? "", "number")),
    field("Preis bis (€)", input("price_max", search?.price_max ?? "", "number")),
    field("Region / Standort", select("location", locationOptions, search?.location ?? "")),
    field("Kategorie", select("marketplace_category", categoryOptions, categoryValue)),
    field("Standard-Template", select("default_template_id", templateOptions, search?.default_template_id ? String(search.default_template_id) : "")),
    field("Live-Überwachung aktiv", enabled),
  );
  const error = element("p", "form-error");
  const actions = element("div", "actions form-actions");
  const cancel = element("button", "button secondary", "Abbrechen");
  cancel.type = "button";
  cancel.addEventListener("click", close);
  const submit = element("button", "button primary", search ? "Änderungen speichern" : "Suche erstellen");
  submit.type = "submit";
  actions.append(cancel, submit);
  form.append(error, actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const data = new FormData(form);
    const name = String(data.get("name") ?? "").trim();
    const query = String(data.get("query") ?? "").trim();
    const priceMin = String(data.get("price_min") ?? "");
    const priceMax = String(data.get("price_max") ?? "");
    if (!name) { error.textContent = "Bitte gib der Suche einen verständlichen Namen."; return; }
    if (!query) { error.textContent = "Bitte gib einen Suchbegriff ein."; return; }
    if (priceMin && priceMax && Number(priceMin) > Number(priceMax)) { error.textContent = "Der Mindestpreis darf nicht über dem Höchstpreis liegen."; return; }
    const category = String(data.get("marketplace_category") ?? "");
    const templateId = String(data.get("default_template_id") ?? "");
    const payload = {
      name,
      category: "marketplace",
      query,
      price_min: priceMin || null,
      price_max: priceMax || null,
      location: String(data.get("location") ?? "") || null,
      category_filters: category ? { marketplace_category: category } : {},
      enabled: enabled.checked,
      default_template_id: templateId ? Number(templateId) : null,
    };
    submit.disabled = true;
    try {
      if (search) await api.updateSearch(search.id, payload);
      else await api.createSearch(payload);
      close();
      await refresh(false);
    } catch (caught) {
      error.textContent = caught instanceof Error ? caught.message : "Die Suche konnte nicht gespeichert werden.";
      submit.disabled = false;
    }
  });
  body.append(form);
  form.querySelector<HTMLInputElement>("[name=name]")?.focus();
}

const placeholders = [
  ["[Name]", "Verkäufer/Anbieter"], ["[Artikel]", "natürliche Artikelphrase"],
  ["[Artikelname]", "Artikelbezeichnung ohne der/die/das"],
  ["[Preis]", "Preis"], ["[Ort]", "Standort"], ["[Zustand]", "Zustand"], ["[URL]", "Inserat-Link"],
] as const;

function openTemplateEditor(template?: MessageTemplate, seed?: { name: string; body: string }): void {
  const { body, close } = modal(template ? "Template bearbeiten" : "Neues Template");
  const form = element("form", "template-form");
  const name = input("name", template?.name ?? seed?.name ?? "");
  const textarea = element("textarea");
  textarea.name = "body";
  textarea.rows = 10;
  textarea.value = template?.body ?? seed?.body ?? "Hallo [Name],\n\nist [Artikel] noch verfügbar?";
  const chips = element("div", "placeholder-list");
  for (const [placeholder, description] of placeholders) {
    const chip = element("button", "placeholder-chip", `${placeholder} · ${description}`);
    chip.type = "button";
    chip.addEventListener("click", () => {
      const start = textarea.selectionStart;
      textarea.setRangeText(placeholder, start, textarea.selectionEnd, "end");
      textarea.focus();
    });
    chips.append(chip);
  }
  const info = element("div", "template-help");
  info.append(element("h3", "", "Verfügbare Platzhalter"), chips, element("p", "subtle", "[Artikel] enthält eine natürliche deutsche Artikelphrase; [Artikelname] nur die Produktbezeichnung. Bei unsicherem Produkttyp wird für [Artikel] „der Artikel“ verwendet."));
  const error = element("p", "form-error");
  const actions = element("div", "actions form-actions");
  const cancel = element("button", "button secondary", "Abbrechen");
  cancel.type = "button";
  cancel.addEventListener("click", close);
  const save = element("button", "button primary", "Template speichern");
  save.type = "submit";
  actions.append(cancel, save);
  form.append(field("Name", name), field("Nachricht", textarea), info, error, actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!name.value.trim() || !textarea.value.trim()) { error.textContent = "Name und Nachricht dürfen nicht leer sein."; return; }
    save.disabled = true;
    try {
      if (template) await api.updateTemplate(template.id, { name: name.value.trim(), body: textarea.value });
      else await api.createTemplate({ name: name.value.trim(), body: textarea.value });
      close();
      await refresh(false);
    } catch (caught) {
      error.textContent = caught instanceof Error ? caught.message : "Das Template konnte nicht gespeichert werden.";
      save.disabled = false;
    }
  });
  body.append(form);
  name.focus();
}

function openMessageDialog(listing: Listing): void {
  const { body } = modal(`Nachricht für ${listing.title}`);
  if (!snapshot!.templates.length) {
    body.append(element("p", "empty-state", "Lege zuerst ein Template an."));
    return;
  }
  const templateSelect = select(
    "template",
    snapshot!.templates.map((template) => ({ label: template.name, value: String(template.id) })),
    String(chooseDefaultTemplate(listing, snapshot!.searches, snapshot!.templates)),
  );
  const preview = element("textarea", "rendered-preview");
  preview.readOnly = true;
  preview.rows = 9;
  const error = element("p", "form-error");
  const copy = element("button", "button primary", "Text kopieren");
  copy.disabled = true;
  const open = element("button", "button secondary", "Inserat öffnen");
  open.addEventListener("click", () => window.open(listing.url, "_blank", "noopener"));
  const render = async () => {
    copy.disabled = true;
    error.textContent = "";
    preview.value = "Vorschau wird erstellt …";
    try {
      const result = await api.renderTemplate(Number(templateSelect.value), listing.listing_id);
      preview.value = result.rendered_text;
      copy.disabled = false;
    } catch (caught) {
      preview.value = "";
      error.textContent = caught instanceof Error ? caught.message : "Die Vorschau konnte nicht erstellt werden.";
    }
  };
  templateSelect.addEventListener("change", () => void render());
  copy.addEventListener("click", async () => {
    try {
      await copyPreparedMessage(preview.value);
      copy.textContent = "Kopiert ✓";
      window.setTimeout(() => { copy.textContent = "Text kopieren"; }, 1800);
    } catch {
      error.textContent = "Der Text konnte nicht in die Zwischenablage kopiert werden.";
    }
  });
  const actions = element("div", "actions");
  actions.append(copy, open);
  body.append(field("Template auswählen", templateSelect), element("p", "subtle", "Die Vorschau wird sicher im lokalen Agenten erstellt."), preview, error, actions, element("p", "manual-note dialog-note", "Du versendest die Nachricht anschließend selbst auf Willhaben."));
  void render();
}

async function mutate(action: () => Promise<unknown>): Promise<void> {
  try {
    await action();
    await refresh(false);
  } catch (error) {
    alert(error instanceof Error ? error.message : "Die Änderung konnte nicht gespeichert werden.");
  }
}

window.addEventListener("hashchange", renderView);
window.addEventListener("keydown", (event) => { if (event.key === "Escape") modalRoot.replaceChildren(); });
void refresh();
window.setInterval(() => void refresh(false), 30_000);
