import { RuntimeApiClient } from "./runtime-api";
import { loadAgentSnapshot } from "./state";
import type {
  AgentSnapshot,
  Listing,
  MessageTemplate,
  NotificationTarget,
  NotificationTargetType,
  Search,
} from "./types";
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
  | {
      reason:
        | "agent_unreachable"
        | "native_host_missing"
        | "native_host_start"
        | "native_host_outdated";
      message: string;
    }
  | null = null;

// Tracks which view is currently built in #content, so periodic status polling
// can tell "still on the same view" (skip rebuilding forms) apart from an actual
// navigation (safe, and expected, to rebuild from fresh data).
let renderedView: View | null = null;

// Dirty flag for the inline SMTP sender form. Set the moment the user edits a
// field; only a successful save (or leaving+re-entering the view) clears it.
// Periodic status polling must never rebuild a dirty form. Per-target editing
// happens in a modal (separate DOM root), so it never needs this protection.
let smtpFormDirty = false;

function anySettingsDirty(): boolean {
  return smtpFormDirty;
}

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

async function refresh(showLoading = true, periodic = false): Promise<void> {
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
  renderView(periodic);
}

function renderView(periodic = false): void {
  const view = currentView();
  activateNavigation(view);
  if (!snapshot) {
    const retry = element("button", "button primary", "Erneut versuchen");
    retry.addEventListener("click", () => void refresh());
    const offline = element("section", "offline-panel");
    const nativeHostMissing = connectionFailure?.reason === "native_host_missing";
    const nativeHostStart = connectionFailure?.reason === "native_host_start";
    const nativeHostOutdated = connectionFailure?.reason === "native_host_outdated";
    offline.append(
      element("div", "offline-icon", "!"),
      element(
        "h1",
        "",
        nativeHostOutdated
          ? "Lokale Verbindung veraltet"
          : nativeHostMissing || nativeHostStart
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
    renderedView = null;
    return;
  }
  const renderers: Record<View, () => void> = {
    overview: renderOverview,
    searches: renderSearches,
    listings: renderListings,
    templates: renderTemplates,
    settings: renderSettings,
  };
  const changedView = view !== renderedView;
  if (view === "settings" && !changedView && periodic) {
    // A periodic status poll landed while the user is still on the settings
    // view: never rebuild it here, that would wipe unsaved input, focus, and
    // cursor position. Settings only (re)load on an actual navigation into
    // the view or an explicit, user-triggered refresh.
  } else {
    if (view === "settings" && changedView) {
      smtpFormDirty = false;
    }
    renderers[view]();
    if (changedView) content.focus({ preventScroll: true });
  }
  renderedView = view;
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
  if (data.status) {
    fragment.append(
      element("p", "app-version-footer", `Willhaben-Suchagent v${data.status.app_version}`),
    );
  }
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

const TARGET_TYPE_INFO: Record<
  NotificationTargetType,
  { heading: string; typeLabel: string; addLabel: string; empty: string }
> = {
  ntfy: {
    heading: "Push / ntfy",
    typeLabel: "Push-Ziel",
    addLabel: "+ Push-Ziel",
    empty: "Noch kein Push-Ziel eingerichtet.",
  },
  discord: {
    heading: "Discord",
    typeLabel: "Discord-Ziel",
    addLabel: "+ Discord-Ziel",
    empty: "Noch kein Discord-Ziel eingerichtet.",
  },
  email: {
    heading: "E-Mail",
    typeLabel: "E-Mail-Empfänger",
    addLabel: "+ E-Mail-Empfänger",
    empty: "Noch kein E-Mail-Empfänger eingerichtet.",
  },
};

function targetStatusBadge(target: NotificationTarget): HTMLElement {
  if (!target.configured) return element("span", "badge muted", "nicht eingerichtet");
  return element(
    "span",
    `badge ${target.enabled ? "success" : "muted"}`,
    target.enabled ? "aktiv" : "eingerichtet, aus",
  );
}

async function refreshTargetsInSnapshot(): Promise<void> {
  snapshot!.notificationTargets = await api.notificationTargets();
}

async function refreshTargetsCard(type: NotificationTargetType): Promise<void> {
  await refreshTargetsInSnapshot();
  const current = document.querySelector<HTMLElement>(`[data-target-card="${type}"]`);
  if (current) current.replaceWith(renderTargetsCard(type));
}

function renderTargetsCard(type: NotificationTargetType): HTMLElement {
  const info = TARGET_TYPE_INFO[type];
  const card = element("section", "card settings-card notification-targets-card");
  card.dataset.targetCard = type;
  card.append(element("h2", "", info.heading));
  const targets = snapshot!.notificationTargets.filter((target) => target.type === type);
  const list = element("div", "target-list");
  if (!targets.length) {
    list.append(element("p", "empty-state", info.empty));
  } else {
    for (const target of targets) {
      list.append(renderTargetRow(type, target));
    }
  }
  const addButton = element("button", "button primary", info.addLabel);
  addButton.type = "button";
  addButton.addEventListener("click", () => openTargetEditor(type));
  card.append(list, addButton);
  return card;
}

function renderTargetRow(type: NotificationTargetType, target: NotificationTarget): HTMLElement {
  const row = element("div", "target-row");
  const nameLine = element("div", "target-row-name");
  nameLine.append(element("strong", "", target.name), targetStatusBadge(target));
  row.append(nameLine);
  if (type === "email" && target.email_address_masked) {
    row.append(element("p", "subtle", target.email_address_masked));
  }
  const result = element("p", "subtle target-row-result");
  const actions = element("div", "actions");
  const editButton = element("button", "button secondary", "Bearbeiten");
  editButton.type = "button";
  editButton.addEventListener("click", () => openTargetEditor(type, target));
  const testButton = element("button", "button secondary", "Testen");
  testButton.type = "button";
  testButton.addEventListener("click", async () => {
    testButton.disabled = true;
    result.textContent = "Test wird gesendet …";
    try {
      const response = await api.testNotificationTarget(target.id);
      result.textContent = `✓ ${response.message}`;
    } catch (error) {
      result.textContent = `✕ ${error instanceof Error ? error.message : "Test fehlgeschlagen."}`;
    } finally {
      testButton.disabled = false;
    }
  });
  const deleteButton = element("button", "button secondary", "Löschen");
  deleteButton.type = "button";
  deleteButton.addEventListener("click", async () => {
    const usageNote =
      target.usage_count > 0
        ? `Dieses Ziel wird von ${target.usage_count} Suche${target.usage_count === 1 ? "" : "n"} verwendet. `
        : "";
    if (!confirm(`${usageNote}„${target.name}“ wirklich löschen?`)) return;
    try {
      await api.deleteNotificationTarget(target.id);
      await refreshTargetsCard(type);
    } catch (error) {
      alert(error instanceof Error ? error.message : "Ziel konnte nicht gelöscht werden.");
    }
  });
  actions.append(editButton, testButton, deleteButton);
  row.append(actions, result);
  return row;
}

function openTargetEditor(type: NotificationTargetType, target?: NotificationTarget): void {
  const typeLabel = TARGET_TYPE_INFO[type].typeLabel;
  const { body, close } = modal(target ? `${typeLabel} bearbeiten` : `Neues ${typeLabel}`);
  const form = element("form", "form-grid");
  const name = input("name", target?.name ?? "");
  const enabled = input("enabled", "", "checkbox");
  enabled.checked = target?.enabled ?? true;
  form.append(field("Name", name));

  let baseUrl: HTMLInputElement | null = null;
  let topic: HTMLInputElement | null = null;
  let token: HTMLInputElement | null = null;
  let webhook: HTMLInputElement | null = null;
  let emailAddress: HTMLInputElement | null = null;

  if (type === "ntfy") {
    baseUrl = input("base_url", target?.ntfy_base_url ?? "https://ntfy.sh");
    topic = input("topic", "");
    topic.placeholder = target?.ntfy_topic_configured
      ? "•••••••••••••••• (gespeichert, leer lassen zum Behalten)"
      : "z. B. mein-privates-topic";
    token = input("token", "", "password");
    token.placeholder = target?.ntfy_token_configured
      ? "•••••••••••••••• (gespeichert, leer lassen zum Behalten)"
      : "Optionaler Zugriffs-Token";
    form.append(field("Server", baseUrl), field("Topic", topic), field("Token (optional)", token));
  } else if (type === "discord") {
    webhook = input("webhook_url", "", "password");
    webhook.placeholder = target?.discord_webhook_configured
      ? "•••••••••••••••• (gespeichert, leer lassen zum Behalten)"
      : "https://discord.com/api/webhooks/…";
    form.append(field("Webhook-URL", webhook));
  } else {
    emailAddress = input("email_address", target?.email_address ?? "");
    form.append(field("E-Mail-Adresse", emailAddress));
  }
  form.append(field("Aktiv", enabled));

  const error = element("p", "form-error");
  const actions = element("div", "actions form-actions");
  const cancel = element("button", "button secondary", "Abbrechen");
  cancel.type = "button";
  cancel.addEventListener("click", close);
  const submit = element("button", "button primary", target ? "Änderungen speichern" : "Ziel erstellen");
  submit.type = "submit";
  actions.append(cancel, submit);
  form.append(error, actions);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (!name.value.trim()) {
      error.textContent = "Bitte gib einen Namen an.";
      return;
    }
    const payload: Record<string, unknown> = { name: name.value.trim(), enabled: enabled.checked };
    if (type === "ntfy") {
      payload.base_url = baseUrl!.value.trim() || "https://ntfy.sh";
      if (topic!.value.trim()) payload.topic = topic!.value.trim();
      if (token!.value.trim()) payload.token = token!.value.trim();
      if (!target && !topic!.value.trim()) {
        error.textContent = "Bitte gib ein ntfy-Topic an.";
        return;
      }
    } else if (type === "discord") {
      if (webhook!.value.trim()) payload.webhook_url = webhook!.value.trim();
      if (!target && !webhook!.value.trim()) {
        error.textContent = "Bitte gib eine Discord-Webhook-URL an.";
        return;
      }
    } else {
      payload.email_address = emailAddress!.value.trim();
      if (!payload.email_address) {
        error.textContent = "Bitte gib eine E-Mail-Adresse an.";
        return;
      }
    }
    submit.disabled = true;
    try {
      if (target) {
        await api.updateNotificationTarget(target.id, payload);
      } else {
        await api.createNotificationTarget({ type, ...payload } as never);
      }
      close();
      await refreshTargetsCard(type);
    } catch (caught) {
      error.textContent =
        caught instanceof Error ? caught.message : "Das Ziel konnte nicht gespeichert werden.";
      submit.disabled = false;
    }
  });
  body.append(form);
  name.focus();
}

function renderSmtpSenderSection(): HTMLElement {
  const settings = snapshot!.settings?.notifications ?? null;
  const card = element("section", "card settings-card");
  card.dataset.smtpCard = "true";
  card.append(
    element("h2", "", "E-Mail-Versand (SMTP)"),
    element("p", "", "Gilt gemeinsam für alle E-Mail-Empfänger."),
  );
  if (!settings) {
    card.append(element("p", "subtle", "Einstellungen sind derzeit nicht verfügbar."));
    return card;
  }
  const form = element("form", "form-grid");
  const smtpHost = input("email_smtp_host", settings.email_smtp_host ?? "");
  const smtpPort = input("email_smtp_port", String(settings.email_smtp_port), "number");
  const smtpUsername = input("email_smtp_username", settings.email_smtp_username ?? "");
  const smtpPassword = input("email_smtp_password", "", "password");
  smtpPassword.placeholder = settings.email_smtp_password_configured
    ? "•••••••••••••••• (gespeichert, leer lassen zum Behalten)"
    : "SMTP-Passwort";
  const fromAddress = input("email_from_address", settings.email_from_address ?? "");
  const encryption = select(
    "email_encryption",
    [
      { label: "STARTTLS", value: "starttls" },
      { label: "SSL/TLS", value: "ssl" },
      { label: "Keine Verschlüsselung", value: "none" },
    ],
    settings.email_encryption,
  );
  form.append(
    field("SMTP-Server", smtpHost),
    field("SMTP-Port", smtpPort),
    field("Benutzername", smtpUsername),
    field("Passwort", smtpPassword),
    field("Absenderadresse", fromAddress),
    field("Verschlüsselung", encryption),
  );
  const dirtyIndicator = element("p", "dirty-indicator", "Ungespeicherte Änderungen");
  dirtyIndicator.hidden = true;
  const result = element("p", "subtle");
  const actions = element("div", "actions");
  const save = element("button", "button primary", "Speichern");
  save.type = "submit";
  actions.append(save);
  form.append(dirtyIndicator, result, actions);
  const markDirty = () => {
    smtpFormDirty = true;
    dirtyIndicator.hidden = false;
  };
  form.addEventListener("input", markDirty);
  form.addEventListener("change", markDirty);
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const payload: Record<string, unknown> = {
      email_smtp_host: smtpHost.value.trim() || null,
      email_smtp_port: Number(smtpPort.value) || 587,
      email_smtp_username: smtpUsername.value.trim() || null,
      email_from_address: fromAddress.value.trim() || null,
      email_encryption: encryption.value,
    };
    if (smtpPassword.value.trim()) payload.email_smtp_password = smtpPassword.value.trim();
    save.disabled = true;
    result.textContent = "Wird gespeichert …";
    try {
      const updated = await api.updateNotificationSettings(payload);
      if (snapshot!.settings) snapshot!.settings.notifications = updated;
      smtpFormDirty = false;
      const current = document.querySelector<HTMLElement>('[data-smtp-card="true"]');
      if (current) current.replaceWith(renderSmtpSenderSection());
    } catch (error) {
      result.textContent =
        error instanceof Error ? error.message : "Einstellung konnte nicht gespeichert werden.";
      save.disabled = false;
    }
  });
  card.append(form);
  return card;
}

function renderNotificationSettings(): HTMLElement {
  const section = element("section", "notification-settings");
  section.append(
    element("h2", "", "Benachrichtigungen"),
    element("p", "", "Wiederverwendbare Push-, Discord- und E-Mail-Ziele einrichten und testen."),
  );
  const grid = element("div", "notification-channel-grid");
  grid.append(
    renderTargetsCard("ntfy"),
    renderTargetsCard("discord"),
    renderTargetsCard("email"),
  );
  section.append(grid, renderSmtpSenderSection());
  return section;
}

function renderDesktopSoundSection(): HTMLElement {
  const soundStatus = snapshot!.status;
  const soundSettings = snapshot!.settings;
  const section = element("div", "desktop-sound-section");
  section.append(element("h2", "", "Desktop-Sound"));
  if (!soundSettings) {
    section.append(element("p", "subtle", "Soundeinstellungen sind derzeit nicht verfügbar."));
    return section;
  }
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
        snapshot!.status.desktop_sound_enabled = snapshot!.settings.desktop_sound_enabled;
        snapshot!.status.desktop_sound_id = snapshot!.settings.desktop_sound_id;
      }
      section.replaceWith(renderDesktopSoundSection());
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
  controls.append(enabledLabel, field("Benachrichtigungston", soundSelect), testSound, result);
  section.append(
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
  return section;
}

function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(String(reader.result ?? ""));
    reader.onerror = () => reject(new Error("Die Datei konnte nicht gelesen werden."));
    reader.readAsText(file);
  });
}

function renderBackupSection(): HTMLElement {
  const section = element("section", "card backup-section");
  section.append(
    element("h2", "", "Daten"),
    element(
      "p",
      "subtle",
      "Passwörter, Tokens und Discord-Webhooks werden aus Sicherheitsgründen nicht exportiert.",
    ),
  );
  const actions = element("div", "backup-actions");
  const exportButton = element("button", "button secondary", "Backup exportieren");
  exportButton.type = "button";
  const importButton = element("button", "button secondary", "Backup importieren");
  importButton.type = "button";
  const fileInput = document.createElement("input");
  fileInput.type = "file";
  fileInput.accept = "application/json";
  fileInput.hidden = true;
  const statusLine = element("p", "subtle backup-status");

  exportButton.addEventListener("click", () => {
    void (async () => {
      exportButton.disabled = true;
      statusLine.textContent = "Backup wird erstellt …";
      try {
        const backup = await api.exportBackup();
        const blob = new Blob([JSON.stringify(backup, null, 2)], {
          type: "application/json",
        });
        const url = URL.createObjectURL(blob);
        const link = document.createElement("a");
        link.href = url;
        link.download = `willhaben-suchagent-backup-${new Date().toISOString().slice(0, 10)}.json`;
        link.click();
        URL.revokeObjectURL(url);
        statusLine.textContent = "Backup wurde heruntergeladen.";
      } catch (error) {
        statusLine.textContent =
          error instanceof Error ? error.message : "Export ist fehlgeschlagen.";
      } finally {
        exportButton.disabled = false;
      }
    })();
  });

  importButton.addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    void (async () => {
      const file = fileInput.files?.[0];
      fileInput.value = "";
      if (!file) return;
      statusLine.textContent = "Backup wird importiert …";
      try {
        const text = await readFileAsText(file);
        const parsed = JSON.parse(text);
        const summary = await api.importBackup(parsed);
        statusLine.textContent =
          `Import abgeschlossen: ${summary.searches_created} Suche(n), ` +
          `${summary.notification_targets_created} Ziel(e), ${summary.templates_created} Vorlage(n) neu angelegt ` +
          `(${summary.searches_skipped + summary.notification_targets_skipped + summary.templates_skipped} bereits vorhanden, übersprungen). ` +
          "Passwörter, Tokens und Discord-Webhooks müssen für importierte Ziele erneut eingerichtet werden. " +
          "Neu geladen erscheinen sie beim nächsten Seitenwechsel.";
      } catch (error) {
        statusLine.textContent =
          error instanceof Error ? error.message : "Backup konnte nicht importiert werden.";
      }
    })();
  });

  actions.append(exportButton, importButton, fileInput);
  section.append(actions, statusLine);
  return section;
}

function renderSettings(): void {
  const safety = element("section", "card settings-card");
  safety.append(
    element("h2", "", "Lokaler Agent"),
    element("p", "", "Verbindung über Firefox Native Messaging"),
    element("code", "api-address", "at.willhaben_suchagent.bridge"),
    element("p", "subtle", "Die Extension spricht ausschließlich mit der installierten lokalen Bridge. Sie benötigt weder Willhaben-Login noch Cookies oder Passwörter."),
    renderDesktopSoundSection(),
    element("h2", "", "Nachrichten bleiben manuell"),
    element("p", "", "Die Extension rendert Text im Agenten, kopiert ihn auf Wunsch und öffnet das Inserat. Sie füllt kein Willhaben-Formular aus und klickt niemals auf Senden."),
  );
  content.replaceChildren(
    pageHeader("Einstellungen", "Verbindung und Sicherheitsprinzipien."),
    renderNotificationSettings(),
    renderBackupSection(),
    safety,
  );
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

const CHANNEL_TOGGLE_GROUPS: Array<{ type: NotificationTargetType; label: string; setupHint: string }> = [
  { type: "ntfy", label: "Handy-Push", setupHint: "Noch kein Push-Ziel eingerichtet." },
  { type: "discord", label: "Discord", setupHint: "Noch kein Discord-Ziel eingerichtet." },
  { type: "email", label: "E-Mail", setupHint: "Noch kein E-Mail-Empfänger eingerichtet." },
];

// New searches start with no target pre-selected: the user must explicitly choose
// which of their existing targets this search should notify. Simpler and safer than
// guessing a "sensible default", and it matches how targets can be shared/renamed
// freely across searches without a search silently gaining a new recipient.
function channelTogglesField(search?: Search): HTMLElement {
  const wrapper = element("div", "channel-toggles");
  wrapper.append(element("span", "field-legend", "Benachrichtigungen für diese Suche"));
  const targets = snapshot!.notificationTargets;
  const selectedIds = new Set(search?.notification_target_ids ?? []);
  for (const group of CHANNEL_TOGGLE_GROUPS) {
    const groupTargets = targets.filter((target) => target.type === group.type);
    const groupWrapper = element("div", "channel-toggle-group");
    groupWrapper.append(element("span", "field-legend", group.label));
    if (!groupTargets.length) {
      groupWrapper.append(element("p", "subtle", group.setupHint));
      const hint = element("a", "text-link channel-setup-hint", "Jetzt einrichten");
      hint.href = "#settings";
      groupWrapper.append(hint);
    } else {
      for (const target of groupTargets) {
        const toggle = input(`notification_target_${target.id}`, "", "checkbox");
        toggle.checked = selectedIds.has(target.id);
        const line = element("label", "channel-toggle-row");
        line.append(toggle, element("span", "", target.name), targetStatusBadge(target));
        groupWrapper.append(line);
      }
    }
    wrapper.append(groupWrapper);
  }
  const soundGroup = element("div", "channel-toggle-group");
  soundGroup.append(element("span", "field-legend", "Desktop-Sound"));
  const soundToggle = input("notify_desktop_sound", "", "checkbox");
  soundToggle.checked = search?.notify_desktop_sound ?? true;
  const soundLine = element("label", "channel-toggle-row");
  soundLine.append(soundToggle, element("span", "", "Ton bei neuem Inserat abspielen"));
  soundGroup.append(soundLine);
  wrapper.append(soundGroup);
  return wrapper;
}

function addCategoryOption(select: HTMLSelectElement, value: string, label: string): void {
  const existing = Array.from(select.options).find((option) => option.value === value);
  if (existing) {
    select.value = value;
    return;
  }
  const option = element("option", "", label);
  option.value = value;
  select.append(option);
  select.value = value;
}

function buildImportUrlSection(fields: {
  query: HTMLInputElement;
  priceMin: HTMLInputElement;
  priceMax: HTMLInputElement;
  location: HTMLSelectElement;
  category: HTMLSelectElement;
}): HTMLElement {
  const section = element("section", "import-url-section");
  const toggle = element("button", "button secondary", "Willhaben-Suchlink übernehmen");
  toggle.type = "button";
  const panel = element("div", "import-url-panel");
  panel.hidden = true;
  toggle.addEventListener("click", () => {
    panel.hidden = !panel.hidden;
  });

  const urlInput = input("import_url", "", "url");
  urlInput.placeholder = "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/…";
  const analyze = element("button", "button secondary", "Link analysieren");
  analyze.type = "button";
  const importError = element("p", "form-error");
  const preview = element("div", "import-preview");
  preview.hidden = true;

  analyze.addEventListener("click", async () => {
    importError.textContent = "";
    preview.hidden = true;
    preview.replaceChildren();
    const url = urlInput.value.trim();
    if (!url) {
      importError.textContent = "Bitte füge zuerst einen Willhaben-Suchlink ein.";
      return;
    }
    analyze.disabled = true;
    try {
      const draft = await api.importSearchUrl(url);
      const rows: Array<[string, string]> = [
        ["Kategorie", draft.category_label ?? "beliebig"],
        ["Suchbegriff", draft.query || "beliebig"],
        [
          "Preis",
          draft.price_min || draft.price_max
            ? `${draft.price_min ?? "0"} – ${draft.price_max ?? "beliebig"} €`
            : "beliebig",
        ],
        ["Region", draft.location ?? "Österreich"],
        ["Sortierung", "Neueste zuerst"],
      ];
      const list = element("dl", "import-preview-list");
      for (const [label, value] of rows) {
        list.append(element("dt", "", label), element("dd", "", value));
      }
      preview.append(element("h3", "", "Importierte Suche"), list);
      if (draft.unsupported_filters.length) {
        const warning = element("div", "import-warning");
        warning.append(
          element(
            "p",
            "",
            "Ein Filter dieser Willhaben-Suche wird derzeit noch nicht unterstützt:",
          ),
        );
        const items = element("ul");
        for (const message of draft.unsupported_filters) items.append(element("li", "", message));
        warning.append(items);
        preview.append(warning);
      }
      const apply = element("button", "button primary", "Übernehmen");
      apply.type = "button";
      apply.addEventListener("click", () => {
        fields.query.value = draft.query;
        fields.priceMin.value = draft.price_min ?? "";
        fields.priceMax.value = draft.price_max ?? "";
        fields.location.value = draft.location ?? "";
        if (draft.category_path) {
          addCategoryOption(
            fields.category,
            draft.category_path,
            draft.category_label ?? draft.category_path,
          );
        } else {
          fields.category.value = "";
        }
        panel.hidden = true;
      });
      preview.append(apply);
      preview.hidden = false;
    } catch (caught) {
      importError.textContent =
        caught instanceof Error ? caught.message : "Der Willhaben-Link konnte nicht analysiert werden.";
    } finally {
      analyze.disabled = false;
    }
  });

  panel.append(field("Willhaben-Suchlink", urlInput), analyze, importError, preview);
  section.append(toggle, panel);
  return section;
}

function openSearchEditor(search?: Search): void {
  const { body, close } = modal(search ? "Suche bearbeiten" : "Neue Marketplace-Suche");
  const form = element("form", "form-grid");
  const existingCategoryPath = String(search?.category_filters.marketplace_category ?? "");
  const existingCategoryLabel = String(search?.category_filters.marketplace_category_label ?? "");
  const knownCategoryValues = new Set(snapshot!.options.categories.map((option) => option.value));
  const categoryOptions = [
    { label: "Alle unterstützten Marketplace-Kategorien", value: "" },
    ...snapshot!.options.categories,
  ];
  if (existingCategoryPath && !knownCategoryValues.has(existingCategoryPath)) {
    categoryOptions.push({
      label: existingCategoryLabel || existingCategoryPath,
      value: existingCategoryPath,
    });
  }
  const locationOptions = [{ label: "Ganz Österreich", value: "" }, ...snapshot!.options.locations];
  const templateOptions = [
    { label: "Kein Standard-Template", value: "" },
    ...snapshot!.templates.map((template) => ({ label: template.name, value: String(template.id) })),
  ];
  const enabled = input("enabled", "", "checkbox");
  enabled.checked = search?.enabled ?? true;
  const queryInput = input("query", search?.query ?? "");
  const priceMinInput = input("price_min", search?.price_min ?? "", "number");
  const priceMaxInput = input("price_max", search?.price_max ?? "", "number");
  const locationSelect = select("location", locationOptions, search?.location ?? "");
  const categorySelect = select("marketplace_category", categoryOptions, existingCategoryPath);
  if (!search) {
    form.append(
      buildImportUrlSection({
        query: queryInput,
        priceMin: priceMinInput,
        priceMax: priceMaxInput,
        location: locationSelect,
        category: categorySelect,
      }),
    );
  }
  form.append(
    field("Name der Suche", input("name", search?.name ?? "")),
    field("Suchbegriff (optional bei konkreter Kategorie)", queryInput),
    field("Preis von (€)", priceMinInput),
    field("Preis bis (€)", priceMaxInput),
    field("Region / Standort", locationSelect),
    field("Kategorie", categorySelect),
    field("Standard-Template", select("default_template_id", templateOptions, search?.default_template_id ? String(search.default_template_id) : "")),
    field("Live-Überwachung aktiv", enabled),
  );
  form.append(channelTogglesField(search));
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
    const category = String(data.get("marketplace_category") ?? "");
    if (!name) { error.textContent = "Bitte gib der Suche einen verständlichen Namen."; return; }
    if (!query && !category) { error.textContent = "Bitte gib einen Suchbegriff oder eine konkrete Kategorie an."; return; }
    if (priceMin && priceMax && Number(priceMin) > Number(priceMax)) { error.textContent = "Der Mindestpreis darf nicht über dem Höchstpreis liegen."; return; }
    const templateId = String(data.get("default_template_id") ?? "");
    const categoryLabel = categorySelect.selectedOptions[0]?.textContent ?? "";
    const notificationTargetIds = snapshot!.notificationTargets
      .filter((target) => data.get(`notification_target_${target.id}`) !== null)
      .map((target) => target.id);
    const payload = {
      name,
      category: "marketplace",
      query,
      price_min: priceMin || null,
      price_max: priceMax || null,
      location: String(data.get("location") ?? "") || null,
      category_filters: category
        ? { marketplace_category: category, marketplace_category_label: categoryLabel }
        : {},
      enabled: enabled.checked,
      default_template_id: templateId ? Number(templateId) : null,
      notification_target_ids: notificationTargetIds,
      notify_desktop_sound: data.get("notify_desktop_sound") !== null,
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

let suppressNextHashchange = false;

window.addEventListener("hashchange", () => {
  if (suppressNextHashchange) {
    suppressNextHashchange = false;
    return;
  }
  const view = currentView();
  if (renderedView === "settings" && view !== "settings" && anySettingsDirty()) {
    const proceed = confirm(
      "Es gibt ungespeicherte Änderungen bei den Benachrichtigungseinstellungen. Trotzdem verlassen?",
    );
    if (!proceed) {
      suppressNextHashchange = true;
      location.hash = "settings";
      return;
    }
  }
  renderView();
});
window.addEventListener("keydown", (event) => { if (event.key === "Escape") modalRoot.replaceChildren(); });
void refresh();
window.setInterval(() => void refresh(false, true), 30_000);
