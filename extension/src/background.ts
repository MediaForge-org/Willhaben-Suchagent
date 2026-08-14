import { handleApiBrokerRequest } from "./api-broker";
import { NativeApiClient } from "./native-api";

const api = new NativeApiClient();

browser.runtime.onMessage.addListener((message: unknown) =>
  handleApiBrokerRequest(message, api),
);
