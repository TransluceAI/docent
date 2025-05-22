import axios from 'axios';

import { BASE_URL } from '@/app/constants';

import socketService from './socketService';

// Utility function used by the request interceptor. It guarantees the
// websocket is connected (or tries to reconnect). If we fail to establish
// the connection we abort the HTTP request.
const ensureWebsocketConnected = async () => {
  try {
    await socketService.ensureConnected();
  } catch (err) {
    // Re-throw so that Axios cancels the request chain with a descriptive error
    throw new Error(
      `WebSocket connection unavailable. Aborting HTTP request. Reason: ${
        (err as Error).message
      }`
    );
  }
};

export const apiBaseClient = axios.create({
  baseURL: `${BASE_URL}`,
  headers: {
    'Content-Type': 'application/json',
  },
});
apiBaseClient.interceptors.request.use(async (config) => {
  await ensureWebsocketConnected();
  return config;
});

export const apiRestClient = axios.create({
  baseURL: `${BASE_URL}/rest`,
  headers: {
    'Content-Type': 'application/json',
  },
});
apiRestClient.interceptors.request.use(async (config) => {
  await ensureWebsocketConnected();
  return config;
});
