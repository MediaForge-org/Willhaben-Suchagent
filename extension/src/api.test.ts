import { expect, test, vi } from "vitest";

import { ApiClient } from "./api";
import type { ApiError } from "./api";
import { listing, search, status, template } from "./test-fixtures";

function response(body: unknown, statusCode = 200): Response {
  return new Response(statusCode === 204 ? null : JSON.stringify(body), {
    status: statusCode,
    headers: { "Content-Type": "application/json" },
  });
}

test("API client loads status, searches, listings and templates", async () => {
  const fetchMock = vi.fn(async (url: string | URL | Request) => {
    const path = String(url);
    if (path.endsWith("/api/v1/status")) return response(status);
    if (path.endsWith("/api/v1/searches")) return response([search]);
    if (path.includes("/api/v1/listings/recent")) return response([listing]);
    return response([template]);
  });
  const api = new ApiClient("http://127.0.0.1:8000", fetchMock as typeof fetch);

  expect((await api.status()).scheduler_running).toBe(true);
  expect((await api.searches())[0]?.name).toBe("ThinkPad in Wien");
  expect((await api.recentListings())[0]?.article_label).toBe("Lenovo ThinkPad T14 G3");
  expect((await api.templates())[0]?.name).toBe("Kaufinteresse");
});

test("API client sends template selection to backend render endpoint", async () => {
  const fetchMock = vi.fn(async (_url: string | URL | Request, init?: RequestInit) => {
    expect(init?.method).toBe("POST");
    expect(JSON.parse(String(init?.body))).toEqual({ listing_id: 9 });
    return response({ rendered_text: "Hallo Max" });
  });
  const api = new ApiClient("http://127.0.0.1:8000", fetchMock as typeof fetch);
  expect((await api.renderTemplate(2, 9)).rendered_text).toBe("Hallo Max");
  expect(String(fetchMock.mock.calls[0]?.[0])).toContain("/templates/2/render");
});

test("API client exposes a concise API validation error", async () => {
  const api = new ApiClient(
    "http://127.0.0.1:8000",
    vi.fn(async () => response({ detail: "Der Mindestpreis ist zu hoch." }, 422)) as typeof fetch,
  );
  await expect(api.createSearch({})).rejects.toMatchObject({
    message: "Der Mindestpreis ist zu hoch.",
    status: 422,
  } satisfies Partial<ApiError>);
});
