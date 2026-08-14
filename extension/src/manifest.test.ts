// @vitest-environment node

import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { resolve } from "node:path";

import { afterAll, beforeAll, expect, test } from "vitest";
import { build } from "vite";

interface ExtensionManifest {
  permissions?: string[];
  host_permissions?: string[];
  content_security_policy?: {
    extension_pages?: string;
  };
  background?: {
    scripts?: string[];
    type?: string;
  };
}

let buildDirectory: string;
let manifest: ExtensionManifest;

beforeAll(async () => {
  buildDirectory = await mkdtemp(resolve(tmpdir(), "willhaben-extension-manifest-"));
  await build({
    configFile: resolve(import.meta.dirname, "../vite.config.ts"),
    logLevel: "silent",
    build: {
      outDir: buildDirectory,
      emptyOutDir: true,
    },
  });
  manifest = JSON.parse(
    await readFile(resolve(buildDirectory, "manifest.json"), "utf8"),
  ) as ExtensionManifest;
});

afterAll(async () => {
  await rm(buildDirectory, { recursive: true, force: true });
});

test("built Firefox manifest uses only clipboard and native-messaging permissions", async () => {
  const extensionPolicy = manifest.content_security_policy?.extension_pages;

  expect(extensionPolicy).toBe("script-src 'self'; object-src 'none'");
  expect(extensionPolicy).not.toContain("upgrade-insecure-requests");
  expect(manifest.host_permissions).toBeUndefined();
  expect(manifest.permissions).toEqual(["clipboardWrite", "nativeMessaging"]);
  expect(manifest.background).toEqual({
    scripts: ["background.js"],
    type: "module",
  });
  const background = await readFile(resolve(buildDirectory, "background.js"), "utf8");
  expect(background).toContain("api_broker_request");
  expect(background).toContain("connectNative");
  expect(background).not.toContain("sendNativeMessage");
  expect(background).toContain("at.willhaben_suchagent.bridge");
  expect(background).not.toMatch(/\bfetch\s*\(/);
  expect(background).not.toContain("http://127.0.0.1:8000");
  expect(background).not.toContain("http://localhost:8000");
});

test("popup and dashboard message the background and contain no direct HTTP transport", async () => {
  const [popupSource, dashboardSource, stateSource, backgroundSource] = await Promise.all([
    readFile(resolve(import.meta.dirname, "popup.ts"), "utf8"),
    readFile(resolve(import.meta.dirname, "dashboard.ts"), "utf8"),
    readFile(resolve(import.meta.dirname, "state.ts"), "utf8"),
    readFile(resolve(import.meta.dirname, "background.ts"), "utf8"),
  ]);

  expect(popupSource).toContain("RuntimeApiClient");
  expect(popupSource).toContain('addEventListener("pagehide"');
  expect(dashboardSource).toContain("RuntimeApiClient");
  for (const source of [popupSource, dashboardSource, stateSource, backgroundSource]) {
    expect(source).not.toContain("new ApiClient");
    expect(source).not.toMatch(/\bfetch\s*\(/);
  }
  expect(backgroundSource).toContain("NativeApiClient");
  expect(backgroundSource).not.toContain('from "./api"');

  const assetNames = await readdir(resolve(buildDirectory, "assets"));
  const javascriptAssets = await Promise.all(
    assetNames
      .filter((name) => name.endsWith(".js"))
      .map((name) => readFile(resolve(buildDirectory, "assets", name), "utf8")),
  );
  for (const asset of javascriptAssets) {
    expect(asset).not.toMatch(/\bfetch\s*\(/);
    expect(asset).not.toContain("/api/v1/");
  }
});
