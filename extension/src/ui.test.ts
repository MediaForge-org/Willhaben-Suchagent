import { expect, test, vi } from "vitest";

import {
  chooseDefaultTemplate,
  copyPreparedMessage,
  formatPrice,
  previewDesktopSound,
  relativeTime,
  renderSearchList,
  renderTemplateList,
} from "./ui";
import { listing, search, template } from "./test-fixtures";

test("search display uses product wording and hides internal ids", () => {
  const view = renderSearchList([search]);
  expect(view.textContent).toContain("ThinkPad in Wien");
  expect(view.textContent).toContain("Live: EIN");
  expect(view.textContent).toContain("Marketplace · ThinkPad");
  expect(view.textContent).not.toContain("computer-software-5824");
  expect(view.textContent).not.toContain("#4");
});

test("template list shows body and management actions", () => {
  const view = renderTemplateList([template]);
  expect(view.textContent).toContain("Kaufinteresse");
  expect(view.textContent).toContain("Hallo [Name]");
  expect(view.querySelectorAll("button")).toHaveLength(3);
});

test("listing chooses the assigned search template and otherwise first template", () => {
  expect(chooseDefaultTemplate(listing, [search], [template])).toBe(2);
  expect(chooseDefaultTemplate(listing, [{ ...search, default_template_id: null }], [template])).toBe(2);
  expect(chooseDefaultTemplate(listing, [search], [])).toBeNull();
});

test("copy workflow writes exactly the rendered backend preview", async () => {
  const clipboard = { writeText: vi.fn(async () => undefined) };
  await copyPreparedMessage("Hallo Max,\n\nist der Artikel verfügbar?", clipboard);
  expect(clipboard.writeText).toHaveBeenCalledWith("Hallo Max,\n\nist der Artikel verfügbar?");
});

test("invalid optional price and time values use safe display fallbacks", () => {
  expect(formatPrice("not-a-price")).toBe("Preis nicht angegeben");
  expect(relativeTime("not-a-date")).toBe("noch nicht");
});

test("sound preview sends the variant selected by the test button", async () => {
  const api = {
    testDesktopSound: vi.fn(async () => ({
      status: "played",
      message: "Pop wurde abgespielt",
    })),
  };

  await expect(previewDesktopSound(api, "pop")).resolves.toMatchObject({
    status: "played",
  });
  expect(api.testDesktopSound).toHaveBeenCalledExactlyOnceWith("pop");
});
