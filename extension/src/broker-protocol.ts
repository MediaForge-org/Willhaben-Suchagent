export type ApiBrokerRequest =
  | { type: "api.status" }
  | { type: "api.settings.get" }
  | {
      type: "api.settings.update";
      payload: { desktop_sound_enabled?: boolean; desktop_sound_id?: string };
    }
  | { type: "api.searches.list" }
  | { type: "api.listings.recent"; limit?: number }
  | { type: "api.templates.list" }
  | { type: "api.marketplace.options" }
  | { type: "api.search.create"; payload: Record<string, unknown> }
  | { type: "api.search.update"; id: number; payload: Record<string, unknown> }
  | { type: "api.search.delete"; id: number }
  | { type: "api.template.create"; payload: { name: string; body: string } }
  | {
      type: "api.template.update";
      id: number;
      payload: { name?: string; body?: string };
    }
  | { type: "api.template.delete"; id: number }
  | { type: "api.template.render"; templateId: number; listingId: number }
  | { type: "api.desktop_sound.test"; soundId?: string };

export interface NativeRequestEnvelope {
  requestId: string;
  request: ApiBrokerRequest;
}

export interface NativeResponseEnvelope {
  requestId: string;
  response: ApiBrokerResponse;
}

export type ApiBrokerErrorKind =
  | "transport"
  | "http"
  | "data"
  | "broker"
  | "native_host_missing"
  | "native_host_start";

export type ApiBrokerResponse<T = unknown> =
  | { ok: true; data: T }
  | {
      ok: false;
      error: {
        kind: ApiBrokerErrorKind;
        message: string;
        status?: number;
      };
    };

export function brokerOperationName(request: unknown): string {
  if (!isRecord(request) || typeof request.type !== "string") return "unknown";
  return request.type.startsWith("api.") ? request.type.slice(4) : request.type;
}

export function isApiBrokerRequest(value: unknown): value is ApiBrokerRequest {
  if (!isRecord(value) || typeof value.type !== "string") return false;
  switch (value.type) {
    case "api.status":
    case "api.settings.get":
    case "api.searches.list":
    case "api.templates.list":
    case "api.marketplace.options":
      return hasOnlyKeys(value, ["type"]);
    case "api.desktop_sound.test":
      return (
        hasOnlyKeys(value, ["type", "soundId"]) &&
        (value.soundId === undefined || isSoundId(value.soundId))
      );
    case "api.settings.update":
      return (
        hasOnlyKeys(value, ["type", "payload"]) &&
        isSettingsPayload(value.payload)
      );
    case "api.listings.recent":
      return (
        hasOnlyKeys(value, ["type", "limit"]) &&
        (value.limit === undefined || isPositiveInteger(value.limit, 200))
      );
    case "api.search.create":
      return hasOnlyKeys(value, ["type", "payload"]) && isRecord(value.payload);
    case "api.search.update":
      return (
        hasOnlyKeys(value, ["type", "id", "payload"]) &&
        isPositiveInteger(value.id) &&
        isRecord(value.payload)
      );
    case "api.search.delete":
    case "api.template.delete":
      return hasOnlyKeys(value, ["type", "id"]) && isPositiveInteger(value.id);
    case "api.template.create":
      return (
        hasOnlyKeys(value, ["type", "payload"]) &&
        isTemplatePayload(value.payload, true)
      );
    case "api.template.update":
      return (
        hasOnlyKeys(value, ["type", "id", "payload"]) &&
        isPositiveInteger(value.id) &&
        isTemplatePayload(value.payload, false)
      );
    case "api.template.render":
      return (
        hasOnlyKeys(value, ["type", "templateId", "listingId"]) &&
        isPositiveInteger(value.templateId) &&
        isPositiveInteger(value.listingId)
      );
    default:
      return false;
  }
}

export function isNativeResponseEnvelope(value: unknown): value is NativeResponseEnvelope {
  return (
    isRecord(value) &&
    hasOnlyKeys(value, ["requestId", "response"]) &&
    typeof value.requestId === "string" &&
    value.requestId.length > 0 &&
    isApiBrokerResponse(value.response)
  );
}

export function isApiBrokerResponse(value: unknown): value is ApiBrokerResponse {
  if (!isRecord(value) || typeof value.ok !== "boolean") return false;
  if (value.ok) return hasOnlyKeys(value, ["ok", "data"]) && "data" in value;
  if (!hasOnlyKeys(value, ["ok", "error"])) return false;
  if (!isRecord(value.error)) return false;
  if (!hasOnlyKeys(value.error, ["kind", "message", "status"])) return false;
  const validError =
    [
      "transport",
      "http",
      "data",
      "broker",
      "native_host_missing",
      "native_host_start",
    ].includes(String(value.error.kind)) && typeof value.error.message === "string";
  const validStatus =
    value.error.status === undefined ||
    (typeof value.error.status === "number" && Number.isInteger(value.error.status));
  return validError && validStatus;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: string[]): boolean {
  return Object.keys(value).every((key) => allowed.includes(key));
}

function isPositiveInteger(value: unknown, maximum?: number): value is number {
  return (
    typeof value === "number" &&
    Number.isInteger(value) &&
    value >= 1 &&
    (maximum === undefined || value <= maximum)
  );
}

function isTemplatePayload(value: unknown, requireBoth: boolean): boolean {
  if (!isRecord(value)) return false;
  const keys = Object.keys(value);
  if (keys.some((key) => key !== "name" && key !== "body")) return false;
  const validName = value.name === undefined || typeof value.name === "string";
  const validBody = value.body === undefined || typeof value.body === "string";
  return validName && validBody && (requireBoth ? keys.includes("name") && keys.includes("body") : keys.length > 0);
}

function isSettingsPayload(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const keys = Object.keys(value);
  if (
    keys.length === 0 ||
    keys.some(
      (key) => key !== "desktop_sound_enabled" && key !== "desktop_sound_id",
    )
  ) {
    return false;
  }
  return (
    (value.desktop_sound_enabled === undefined ||
      typeof value.desktop_sound_enabled === "boolean") &&
    (value.desktop_sound_id === undefined || isSoundId(value.desktop_sound_id))
  );
}

function isSoundId(value: unknown): value is string {
  return (
    value === "notify" || value === "ping" || value === "pop"
  );
}
