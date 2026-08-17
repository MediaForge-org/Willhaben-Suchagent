import { afterEach, beforeEach, expect, test, vi } from "vitest";

import { listing, notificationSettings, notificationTargets, search, settings, status } from "./test-fixtures";
import type { NotificationTarget } from "./types";

const IPHONE_TEST_URL =
  "https://www.willhaben.at/iad/kaufen-und-verkaufen/marktplatz/apple/iphone-13-mini-5009987" +
  "?keyword=iphone+13+mini&sfId=abc&rows=30&isNavigation=true";

function setupDom(): void {
  document.body.innerHTML = `
    <div class="app-shell">
      <aside class="sidebar">
        <nav id="navigation" aria-label="Hauptnavigation">
          <a href="#overview" data-view="overview">Übersicht</a>
          <a href="#searches" data-view="searches">Meine Suchen</a>
          <a href="#listings" data-view="listings">Neue Inserate</a>
          <a href="#templates" data-view="templates">Templates</a>
          <a href="#settings" data-view="settings">Einstellungen</a>
        </nav>
      </aside>
      <main class="dashboard-main">
        <div id="connection-banner" class="connection-banner" hidden></div>
        <section id="content" tabindex="-1" aria-live="polite"></section>
      </main>
    </div>
    <div id="modal-root"></div>
  `;
}

interface MockOptions {
  statusFactory?: () => typeof status;
  extraEndpointErrorOnSecondCall?: "listings";
  initialTargets?: NotificationTarget[];
}

function createSendMessageMock(options: MockOptions = {}) {
  let call = 0;
  let nextId = 100;
  const targets: NotificationTarget[] = [...(options.initialTargets ?? notificationTargets)];

  return vi.fn(async (message: { type: string; id?: number; payload?: Record<string, unknown> }) => {
    switch (message.type) {
      case "api.status":
        call += 1;
        return { ok: true, data: options.statusFactory ? options.statusFactory() : status };
      case "api.settings.get":
        return { ok: true, data: settings };
      case "api.searches.list":
        return { ok: true, data: [search] };
      case "api.listings.recent":
        if (options.extraEndpointErrorOnSecondCall === "listings" && call > 1) {
          return { ok: false, error: { kind: "data", message: "Inserate konnten nicht geladen werden." } };
        }
        return { ok: true, data: [listing] };
      case "api.templates.list":
        return { ok: true, data: [] };
      case "api.marketplace.options":
        return { ok: true, data: { categories: [], locations: [] } };
      case "api.settings.notifications.update":
        return { ok: true, data: { ...notificationSettings, ...message.payload } };
      case "api.notificationTargets.list":
        return { ok: true, data: targets };
      case "api.notificationTargets.create": {
        const created: NotificationTarget = {
          id: nextId++,
          type: (message.payload?.type as NotificationTarget["type"]) ?? "ntfy",
          name: String(message.payload?.name ?? ""),
          enabled: (message.payload?.enabled as boolean) ?? true,
          configured: true,
          ntfy_base_url: (message.payload?.base_url as string) ?? null,
          ntfy_topic_configured: Boolean(message.payload?.topic),
          ntfy_token_configured: Boolean(message.payload?.token),
          discord_webhook_configured: Boolean(message.payload?.webhook_url),
          email_address: (message.payload?.email_address as string) ?? null,
          email_address_masked: null,
          usage_count: 0,
          created_at: "2026-08-17T00:00:00Z",
          updated_at: "2026-08-17T00:00:00Z",
        };
        targets.push(created);
        return { ok: true, data: created };
      }
      case "api.notificationTargets.update": {
        const index = targets.findIndex((target) => target.id === message.id);
        if (index === -1) return { ok: false, error: { kind: "http", message: "not found", status: 404 } };
        targets[index] = { ...targets[index], ...message.payload } as NotificationTarget;
        return { ok: true, data: targets[index] };
      }
      case "api.notificationTargets.delete": {
        const index = targets.findIndex((target) => target.id === message.id);
        if (index !== -1) targets.splice(index, 1);
        return { ok: true, data: { deleted: true, searches_affected: 0 } };
      }
      case "api.notificationTargets.test":
        return { ok: true, data: { status: "sent", message: "Test erfolgreich" } };
      case "api.backup.export":
        return {
          ok: true,
          data: { format_version: 1, app_version: "1.0.0", searches: [], templates: [], notification_targets: [] },
        };
      case "api.backup.import":
        return {
          ok: true,
          data: {
            templates_created: 1,
            templates_skipped: 0,
            notification_targets_created: 2,
            notification_targets_skipped: 0,
            searches_created: 1,
            searches_skipped: 0,
          },
        };
      case "api.marketplace.import_search_url":
        return {
          ok: true,
          data: {
            category_path: "apple/iphone-13-mini-5009987",
            category_label: "Apple → iPhone 13 Mini",
            query: "iphone 13 mini",
            location: null,
            price_min: null,
            price_max: null,
            unsupported_filters: [],
          },
        };
      default:
        return { ok: true, data: null };
    }
  });
}

async function mountDashboard(sendMessage: ReturnType<typeof createSendMessageMock>): Promise<void> {
  (globalThis as unknown as { browser: unknown }).browser = { runtime: { sendMessage } };
  await import("./dashboard");
  await vi.advanceTimersByTimeAsync(0);
}

function goToSettings(): void {
  location.hash = "#settings";
  window.dispatchEvent(new Event("hashchange"));
}

function buttonWithText(text: string): HTMLButtonElement {
  const button = Array.from(document.querySelectorAll<HTMLButtonElement>("button")).find(
    (candidate) => candidate.textContent === text,
  );
  if (!button) throw new Error(`No button with text "${text}" found`);
  return button;
}

// dashboard.ts registers window-level listeners and a setInterval as an
// import-time side effect and never tears them down (fine for the real,
// single-load extension page). Re-importing it fresh in every test would
// otherwise leave every previous test's listeners/interval still attached to
// the same jsdom `window`, causing cross-test interference. Track and strip
// them here so each test observes exactly one, freshly mounted instance.
let trackedListeners: Array<[string, EventListenerOrEventListenerObject]> = [];
let addEventListenerSpy: ReturnType<typeof vi.spyOn> | null = null;

beforeEach(() => {
  vi.resetModules();
  vi.useFakeTimers();
  location.hash = "";
  setupDom();
  trackedListeners = [];
  const original = window.addEventListener.bind(window);
  addEventListenerSpy = vi
    .spyOn(window, "addEventListener")
    .mockImplementation((type: string, listener: EventListenerOrEventListenerObject, opts?: unknown) => {
      trackedListeners.push([type, listener]);
      original(type, listener, opts as AddEventListenerOptions | boolean | undefined);
    });
});

afterEach(() => {
  for (const [type, listener] of trackedListeners) {
    window.removeEventListener(type, listener);
  }
  addEventListenerSpy?.mockRestore();
  vi.clearAllTimers();
  vi.useRealTimers();
  delete (globalThis as { browser?: unknown }).browser;
});

// -- Dirty-state / periodic-poll safety (still relevant for the inline SMTP form) ------

test("periodic status refresh does not overwrite an in-progress SMTP host field", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const hostInput = document.querySelector<HTMLInputElement>('input[name="email_smtp_host"]')!;
  hostInput.value = "smtp.typing-in-progress.test";
  hostInput.dispatchEvent(new Event("input", { bubbles: true }));

  await vi.advanceTimersByTimeAsync(30_000);

  const afterPoll = document.querySelector<HTMLInputElement>('input[name="email_smtp_host"]')!;
  expect(afterPoll).toBe(hostInput);
  expect(afterPoll.value).toBe("smtp.typing-in-progress.test");
});

test("periodic status refresh does not overwrite an in-progress SMTP password field", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const passwordInput = document.querySelector<HTMLInputElement>('input[name="email_smtp_password"]')!;
  passwordInput.value = "correct horse battery staple";
  passwordInput.dispatchEvent(new Event("input", { bubbles: true }));

  await vi.advanceTimersByTimeAsync(30_000);

  const afterPoll = document.querySelector<HTMLInputElement>('input[name="email_smtp_password"]')!;
  expect(afterPoll).toBe(passwordInput);
  expect(afterPoll.value).toBe("correct horse battery staple");
});

test("focus stays on the field the user is actively editing across a periodic poll", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const hostInput = document.querySelector<HTMLInputElement>('input[name="email_smtp_host"]')!;
  hostInput.focus();
  expect(document.activeElement).toBe(hostInput);

  await vi.advanceTimersByTimeAsync(30_000);

  expect(document.activeElement).toBe(hostInput);
});

test("editing the SMTP form sets the dirty state and shows the indicator", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const hostInput = document.querySelector<HTMLInputElement>('input[name="email_smtp_host"]')!;
  const indicator = hostInput.closest("form")!.querySelector<HTMLElement>(".dirty-indicator")!;
  expect(indicator.hidden).toBe(true);

  hostInput.value = "changed.test";
  hostInput.dispatchEvent(new Event("input", { bubbles: true }));

  expect(indicator.hidden).toBe(false);
});

test("a successful SMTP save clears the dirty state", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const hostInput = document.querySelector<HTMLInputElement>('input[name="email_smtp_host"]')!;
  hostInput.value = "changed.test";
  hostInput.dispatchEvent(new Event("input", { bubbles: true }));
  const form = hostInput.closest("form")!;
  form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await vi.advanceTimersByTimeAsync(0);

  const freshHostInput = document.querySelector<HTMLInputElement>('input[name="email_smtp_host"]')!;
  const freshIndicator = freshHostInput.closest("form")!.querySelector<HTMLElement>(".dirty-indicator")!;
  expect(freshIndicator.hidden).toBe(true);
});

test("after saving, the SMTP password field stays masked and never echoes the typed value", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const passwordInput = document.querySelector<HTMLInputElement>('input[name="email_smtp_password"]')!;
  passwordInput.value = "super-secret-password-value";
  passwordInput.dispatchEvent(new Event("input", { bubbles: true }));
  const form = passwordInput.closest("form")!;
  form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await vi.advanceTimersByTimeAsync(0);

  const freshPasswordInput = document.querySelector<HTMLInputElement>('input[name="email_smtp_password"]')!;
  expect(freshPasswordInput.value).toBe("");
  expect(document.body.innerHTML).not.toContain("super-secret-password-value");
});

test("agent status (connection banner) can still update while the SMTP form is dirty", async () => {
  const sendMessage = createSendMessageMock({ extraEndpointErrorOnSecondCall: "listings" });
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const hostInput = document.querySelector<HTMLInputElement>('input[name="email_smtp_host"]')!;
  hostInput.value = "still-typing.test";
  hostInput.dispatchEvent(new Event("input", { bubbles: true }));

  const banner = document.querySelector<HTMLElement>("#connection-banner")!;
  expect(banner.hidden).toBe(true);

  await vi.advanceTimersByTimeAsync(30_000);

  expect(banner.hidden).toBe(false);
  const afterPoll = document.querySelector<HTMLInputElement>('input[name="email_smtp_host"]')!;
  expect(afterPoll.value).toBe("still-typing.test");
});

test("clicking a non-submit button (target test) does not submit any form", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const testButton = buttonWithText("Testen");
  expect(testButton.type).toBe("button");
  testButton.click();
  await vi.advanceTimersByTimeAsync(0);

  expect(sendMessage).toHaveBeenCalledWith(
    expect.objectContaining({ type: "api.notificationTargets.test" }),
  );
  expect(sendMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "api.settings.notifications.update" }),
  );
});

test("internal navigation between dashboard views does not require a browser reload", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);

  location.hash = "#searches";
  window.dispatchEvent(new Event("hashchange"));

  expect(document.querySelector("#content")!.textContent).toContain("Meine Suchen");
});

// -- Notification target list / CRUD ----------------------------------------------------

test("settings page lists existing targets per channel with status badges", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const contentText = document.querySelector("#content")!.textContent!;
  expect(contentText).toContain("Maxim iPhone");
  expect(contentText).toContain("Papa – Willhaben");
  expect(contentText).toContain("Papa");
});

test("a channel with no targets shows the 'not yet configured' hint", async () => {
  const sendMessage = createSendMessageMock({ initialTargets: [] });
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const contentText = document.querySelector("#content")!.textContent!;
  expect(contentText).toContain("Noch kein Push-Ziel eingerichtet.");
  expect(contentText).toContain("Noch kein Discord-Ziel eingerichtet.");
  expect(contentText).toContain("Noch kein E-Mail-Empfänger eingerichtet.");
});

test("creating a new ntfy target opens a modal, never navigates, and appears in the list", async () => {
  const sendMessage = createSendMessageMock({ initialTargets: [] });
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  buttonWithText("+ Push-Ziel").click();
  const nameInput = document.querySelector<HTMLInputElement>('#modal-root input[name="name"]')!;
  const topicInput = document.querySelector<HTMLInputElement>('#modal-root input[name="topic"]')!;
  nameInput.value = "Maxim iPhone";
  topicInput.value = "mein-topic";
  const form = nameInput.closest("form")!;
  form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true }));
  await vi.advanceTimersByTimeAsync(0);

  expect(sendMessage).toHaveBeenCalledWith(
    expect.objectContaining({ type: "api.notificationTargets.create" }),
  );
  expect(document.querySelector("#modal-root")!.textContent).toBe("");
  expect(document.querySelector('[data-target-card="ntfy"]')!.textContent).toContain("Maxim iPhone");
});

test("editing a target never echoes its existing secret back into the form", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const editButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("button")).filter(
    (button) => button.textContent === "Bearbeiten",
  );
  editButtons[0]!.click();

  const topicInput = document.querySelector<HTMLInputElement>('#modal-root input[name="topic"]')!;
  expect(topicInput.value).toBe("");
  expect(topicInput.placeholder).toContain("gespeichert");
});

test("deleting a target asks for confirmation and removes it from the list", async () => {
  const sendMessage = createSendMessageMock();
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const deleteButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("button")).filter(
    (button) => button.textContent === "Löschen",
  );
  deleteButtons[0]!.click();
  await vi.advanceTimersByTimeAsync(0);

  expect(confirmSpy).toHaveBeenCalled();
  expect(sendMessage).toHaveBeenCalledWith(
    expect.objectContaining({ type: "api.notificationTargets.delete" }),
  );
  confirmSpy.mockRestore();
});

test("declining the delete confirmation keeps the target", async () => {
  const sendMessage = createSendMessageMock();
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const deleteButtons = Array.from(document.querySelectorAll<HTMLButtonElement>("button")).filter(
    (button) => button.textContent === "Löschen",
  );
  deleteButtons[0]!.click();
  await vi.advanceTimersByTimeAsync(0);

  expect(sendMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "api.notificationTargets.delete" }),
  );
  confirmSpy.mockRestore();
});

// -- Search editor: multi-target selection -----------------------------------------------

function openNewSearchModal(): void {
  buttonWithText("+ Neue Suche").click();
}

test("search editor lists each configured target as its own checkbox, independent per channel", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  location.hash = "#searches";
  window.dispatchEvent(new Event("hashchange"));
  openNewSearchModal();

  const modalText = document.querySelector("#modal-root")!.textContent!;
  expect(modalText).toContain("Maxim iPhone");
  expect(modalText).toContain("Papa – Willhaben");
  expect(modalText).toContain("Papa");
  expect(
    document.querySelector<HTMLInputElement>('#modal-root input[name="notification_target_1"]'),
  ).not.toBeNull();
  expect(
    document.querySelector<HTMLInputElement>('#modal-root input[name="notification_target_2"]'),
  ).not.toBeNull();
});

test("new searches start with no target pre-selected (explicit opt-in)", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  location.hash = "#searches";
  window.dispatchEvent(new Event("hashchange"));
  openNewSearchModal();

  const toggle = document.querySelector<HTMLInputElement>(
    '#modal-root input[name="notification_target_1"]',
  )!;
  expect(toggle.checked).toBe(false);
});

test("existing search assignments are loaded when editing", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  location.hash = "#searches";
  window.dispatchEvent(new Event("hashchange"));
  await vi.advanceTimersByTimeAsync(0);

  buttonWithText("Bearbeiten").click();

  const toggle = document.querySelector<HTMLInputElement>(
    '#modal-root input[name="notification_target_1"]',
  )!;
  expect(toggle.checked).toBe(true);
});

// -- Willhaben URL import continues to work alongside the new target selection ----------

test("import URL flow: preview shows the deep category and hides technical parameters", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  location.hash = "#searches";
  window.dispatchEvent(new Event("hashchange"));
  openNewSearchModal();

  buttonWithText("Willhaben-Suchlink übernehmen").click();
  const urlInput = document.querySelector<HTMLInputElement>('input[name="import_url"]')!;
  urlInput.value = IPHONE_TEST_URL;
  buttonWithText("Link analysieren").click();
  await vi.advanceTimersByTimeAsync(0);

  const modalText = document.querySelector("#modal-root")!.textContent!;
  expect(modalText).toContain("Apple → iPhone 13 Mini");
  expect(modalText).not.toContain("sfId");
  expect(modalText).not.toContain("isNavigation");
  expect(modalText).not.toContain("5009987");
});

test("import URL flow: 'Übernehmen' fills the search form but creates nothing until confirmed, and keeps target checkboxes", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  location.hash = "#searches";
  window.dispatchEvent(new Event("hashchange"));
  openNewSearchModal();

  buttonWithText("Willhaben-Suchlink übernehmen").click();
  const urlInput = document.querySelector<HTMLInputElement>('input[name="import_url"]')!;
  urlInput.value = IPHONE_TEST_URL;
  buttonWithText("Link analysieren").click();
  await vi.advanceTimersByTimeAsync(0);

  buttonWithText("Übernehmen").click();

  const categorySelect = document.querySelector<HTMLSelectElement>(
    'select[name="marketplace_category"]',
  )!;
  const queryInput = document.querySelector<HTMLInputElement>('input[name="query"]')!;
  expect(categorySelect.value).toBe("apple/iphone-13-mini-5009987");
  expect(queryInput.value).toBe("iphone 13 mini");
  expect(sendMessage).not.toHaveBeenCalledWith(
    expect.objectContaining({ type: "api.search.create" }),
  );

  // The existing per-search notification toggles must still be present and usable
  // after applying an import — the import must not remove or reset them.
  expect(document.querySelector('input[name="notification_target_1"]')).not.toBeNull();
  expect(document.querySelector('input[name="notify_desktop_sound"]')).not.toBeNull();
});

// -- Backup / Export / Import ------------------------------------------------------------

test("'Backup exportieren' downloads the exported document without exposing secrets", async () => {
  const createObjectURL = vi.fn(() => "blob:mock-url");
  const revokeObjectURL = vi.fn();
  vi.stubGlobal("URL", { ...URL, createObjectURL, revokeObjectURL });
  const clickSpy = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {});
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  buttonWithText("Backup exportieren").click();
  await vi.advanceTimersByTimeAsync(0);

  expect(sendMessage).toHaveBeenCalledWith(
    expect.objectContaining({ type: "api.backup.export" }),
  );
  expect(createObjectURL).toHaveBeenCalled();
  expect(clickSpy).toHaveBeenCalled();
  expect(revokeObjectURL).toHaveBeenCalledWith("blob:mock-url");
  expect(document.querySelector(".backup-status")?.textContent).toBe(
    "Backup wurde heruntergeladen.",
  );

  clickSpy.mockRestore();
  vi.unstubAllGlobals();
});

test("'Backup importieren' sends the parsed file and reports what was created", async () => {
  const sendMessage = createSendMessageMock();
  await mountDashboard(sendMessage);
  goToSettings();
  await vi.advanceTimersByTimeAsync(0);

  const fileInput = document.querySelector<HTMLInputElement>('input[type="file"]')!;
  const file = new File(
    [JSON.stringify({ format_version: 1, searches: [] })],
    "backup.json",
    { type: "application/json" },
  );
  Object.defineProperty(fileInput, "files", { value: [file], configurable: true });
  fileInput.dispatchEvent(new Event("change"));
  await vi.advanceTimersByTimeAsync(50);

  expect(sendMessage).toHaveBeenCalledWith(
    expect.objectContaining({
      type: "api.backup.import",
      payload: expect.objectContaining({ format_version: 1 }),
    }),
  );
  const statusText = document.querySelector(".backup-status")?.textContent ?? "";
  expect(statusText).toContain("1 Suche(n)");
  expect(statusText).toContain("erneut eingerichtet werden");
});
