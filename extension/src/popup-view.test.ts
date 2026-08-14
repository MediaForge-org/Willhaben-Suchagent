import { expect, test, vi } from "vitest";

import { renderNativeHostPopup, renderOnlinePopup } from "./popup-view";
import { listing, status } from "./test-fixtures";

test("popup renders online status and listing when both are available", () => {
  const root = document.createElement("main");

  renderOnlinePopup(root, status, listing);

  expect(root.textContent).toContain("Überwachung aktiv");
  expect(root.textContent).toContain("Lenovo ThinkPad T14 G3");
  expect(root.textContent).not.toContain("Agent nicht erreichbar");
});

test("popup renders online status without listings", () => {
  const root = document.createElement("main");

  renderOnlinePopup(root, status, null, { listings: "Listings unavailable" });

  expect(root.textContent).toContain("Überwachung aktiv");
  expect(root.textContent).toContain("Letzte Inserate konnten nicht geladen werden.");
  expect(root.textContent).not.toContain("Agent nicht erreichbar");
});

test("optional listing rendering error never changes online status to offline", () => {
  const root = document.createElement("main");
  const reportError = vi.fn();
  const brokenListing = { ...listing };
  Object.defineProperty(brokenListing, "location", {
    get: () => { throw new Error("Broken optional location"); },
  });

  renderOnlinePopup(root, status, brokenListing, {}, reportError);

  expect(root.textContent).toContain("Überwachung aktiv");
  expect(root.textContent).toContain("Der letzte Fund konnte nicht angezeigt werden.");
  expect(root.textContent).not.toContain("Agent nicht erreichbar");
  expect(reportError).toHaveBeenCalledWith(
    "Listingdarstellung fehlgeschlagen",
    expect.any(Error),
  );
});

test("popup explains a missing native host without claiming the agent is offline", () => {
  const root = document.createElement("main");

  renderNativeHostPopup(root, "Lokale Verbindung ist noch nicht eingerichtet.");

  expect(root.textContent).toContain("Lokale Verbindung fehlt");
  expect(root.textContent).toContain("Lokale Verbindung ist noch nicht eingerichtet.");
  expect(root.textContent).not.toContain("Agent nicht erreichbar");
});
