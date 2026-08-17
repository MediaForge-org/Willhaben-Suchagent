import {
  ApiDataError,
  ApiHttpError,
  ApiNativeHostError,
  type ApiService,
  ApiTransportError,
} from "./api-contract";
import {
  type ApiBrokerRequest,
  type ApiBrokerResponse,
  brokerOperationName,
  isApiBrokerRequest,
} from "./broker-protocol";

export interface BrokerLogger {
  info(message: string): void;
  error(message: string): void;
}

const consoleLogger: BrokerLogger = {
  info: (message) => console.info(message),
  error: (message) => console.error(message),
};

export async function handleApiBrokerRequest(
  message: unknown,
  api: ApiService,
  logger: BrokerLogger = consoleLogger,
): Promise<ApiBrokerResponse> {
  const operation = brokerOperationName(message);
  logger.info(`api_broker_request operation=${operation}`);
  if (!isApiBrokerRequest(message)) {
    logger.error(`api_broker_error operation=${operation} error=unknown_operation`);
    return brokerError("broker", "Unbekannte API-Broker-Operation.");
  }
  try {
    const data = await dispatch(message, api);
    logger.info(`api_broker_success operation=${operation}`);
    return { ok: true, data };
  } catch (error) {
    if (error instanceof ApiTransportError) {
      logger.error(`api_broker_transport_error operation=${operation} error=network`);
      return brokerError("transport", error.message);
    }
    if (error instanceof ApiHttpError) {
      logger.error(`api_broker_http_error operation=${operation} status=${error.status ?? 0}`);
      return brokerError("http", error.message, error.status);
    }
    if (error instanceof ApiNativeHostError) {
      const kind =
        error.reason === "not_installed"
          ? "native_host_missing"
          : error.reason === "outdated"
            ? "native_host_outdated"
            : "native_host_start";
      logger.error(`api_broker_native_host_error operation=${operation} reason=${error.reason}`);
      return brokerError(kind, error.message);
    }
    if (error instanceof ApiDataError) {
      logger.error(`api_broker_data_error operation=${operation} error=invalid_response`);
      return brokerError("data", error.message);
    }
    logger.error(`api_broker_error operation=${operation} error=unexpected`);
    return brokerError("broker", "Die Broker-Anfrage konnte nicht verarbeitet werden.");
  }
}

async function dispatch(request: ApiBrokerRequest, api: ApiService): Promise<unknown> {
  switch (request.type) {
    case "api.status":
      return api.status();
    case "api.settings.get":
      return api.settings();
    case "api.settings.update":
      return api.updateSettings(request.payload);
    case "api.searches.list":
      return api.searches();
    case "api.listings.recent":
      return api.recentListings(request.limit);
    case "api.templates.list":
      return api.templates();
    case "api.marketplace.options":
      return api.marketplaceOptions();
    case "api.search.create":
      return api.createSearch(request.payload);
    case "api.search.update":
      return api.updateSearch(request.id, request.payload);
    case "api.search.delete":
      return api.deleteSearch(request.id);
    case "api.template.create":
      return api.createTemplate(request.payload);
    case "api.template.update":
      return api.updateTemplate(request.id, request.payload);
    case "api.template.delete":
      return api.deleteTemplate(request.id);
    case "api.template.render":
      return api.renderTemplate(request.templateId, request.listingId);
    case "api.desktop_sound.test":
      return api.testDesktopSound(request.soundId);
    case "api.settings.notifications.update":
      return api.updateNotificationSettings(request.payload);
    case "api.marketplace.import_search_url":
      return api.importSearchUrl(request.url);
    case "api.notificationTargets.list":
      return api.notificationTargets();
    case "api.notificationTargets.create":
      return api.createNotificationTarget(
        request.payload as unknown as Parameters<ApiService["createNotificationTarget"]>[0],
      );
    case "api.notificationTargets.update":
      return api.updateNotificationTarget(request.id, request.payload);
    case "api.notificationTargets.delete":
      return api.deleteNotificationTarget(request.id);
    case "api.notificationTargets.test":
      return api.testNotificationTarget(request.id);
    case "api.backup.export":
      return api.exportBackup();
    case "api.backup.import":
      return api.importBackup(
        request.payload as unknown as Parameters<ApiService["importBackup"]>[0],
      );
  }
}

function brokerError(
  kind:
    | "transport"
    | "http"
    | "data"
    | "broker"
    | "native_host_missing"
    | "native_host_start"
    | "native_host_outdated",
  message: string,
  status?: number,
): ApiBrokerResponse {
  return { ok: false, error: { kind, message, ...(status === undefined ? {} : { status }) } };
}
