import { v4 as uuid4 } from 'uuid';

import { BASE_URL } from '@/app/constants';

// This will hold our socket instance
let socket: WebSocket | null = null;
let isConnected = false;
let messageListeners: Array<(event: MessageEvent) => void> = [];
let connectionStatusListeners: Array<(status: boolean) => void> = [];

// Notify all connection status listeners
const notifyConnectionStatusChange = (status: boolean) => {
  connectionStatusListeners.forEach((listener) => listener(status));
};

// Keep track of the last connection parameters for reconnection
let lastCollectionId: string | null = null;
let lastViewId: string | null = null;

/**
 * Ensure the websocket is connected. If it's closed, we try to reconnect
 * using the last successfully-used collectionId and viewId. If we cannot reconnect we
 * throw, allowing the caller (e.g. an axios interceptor) to surface the
 * error.
 */
export const ensureConnected = async (): Promise<void> => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    return;
  }

  if (!lastCollectionId) {
    // If we have never established a connection before, just return and let
    // the caller proceed. Some endpoints (e.g. fetching available eval IDs)
    // do not require an active websocket connection.
    return;
  }

  console.log(
    'Attempting to reconnect to',
    lastCollectionId,
    'with view',
    lastViewId
  );
  await initSocket(lastCollectionId, lastViewId || undefined);
};

// Initialize the WebSocket connection
export const initSocket = (
  collectionId: string,
  viewId?: string
): Promise<void> => {
  return new Promise((resolve, reject) => {
    if (socket && socket.readyState === WebSocket.OPEN) {
      isConnected = true;
      resolve();
      return;
    }

    const baseUrl = `${BASE_URL ? (BASE_URL.startsWith('https') ? 'wss' : 'ws') : 'ws'}://${(BASE_URL || '').replace(/^https?:\/\//, '')}`;
    const viewParam = viewId ? `?view_id=${viewId}` : '';
    const ws = new WebSocket(`${baseUrl}/broker/${collectionId}${viewParam}`);

    ws.onopen = () => {
      console.log(
        'Redux socket connected to collection:',
        collectionId,
        'view:',
        viewId || 'none'
      );
      socket = ws;
      isConnected = true;
      notifyConnectionStatusChange(isConnected);
      lastCollectionId = collectionId;
      lastViewId = viewId || null;
      resolve();
    };

    ws.onclose = () => {
      console.log('Redux socket disconnected');
      isConnected = false;
      socket = null;
      notifyConnectionStatusChange(isConnected);
    };

    ws.onerror = (error) => {
      console.error('Redux socket error:', error);
      isConnected = false;
      notifyConnectionStatusChange(isConnected);
      reject(error);
    };

    // Forward messages to all registered listeners
    ws.onmessage = (event) => {
      messageListeners.forEach((listener) => listener(event));
    };

    socket = ws;
  });
};

// Send a message through the socket
export const send = (action: string, payload: any): boolean => {
  if (socket && socket.readyState === WebSocket.OPEN) {
    console.log('(ws) send_message', { action, payload });
    socket.send(JSON.stringify({ action, payload }));
    return true;
  } else {
    console.error('Redux socket not connected');
    return false;
  }
};

// Generate a task ID (for cancellable operations)
export const generateTaskId = (): string => {
  return uuid4();
};

// Add a message listener
export const addMessageListener = (
  listener: (event: MessageEvent) => void
): void => {
  messageListeners.push(listener);
};

// Remove a message listener
export const removeMessageListener = (
  listener: (event: MessageEvent) => void
): void => {
  messageListeners = messageListeners.filter((l) => l !== listener);
};

// Add a connection status listener
export const addConnectionStatusListener = (
  listener: (status: boolean) => void
): void => {
  connectionStatusListeners.push(listener);
  // Immediately notify with current status
  if (isConnected !== undefined) {
    listener(isConnected);
  }
};

// Remove a connection status listener
export const removeConnectionStatusListener = (
  listener: (status: boolean) => void
): void => {
  connectionStatusListeners = connectionStatusListeners.filter(
    (l) => l !== listener
  );
};

// Check if socket is connected
export const getConnectionStatus = (): boolean => {
  return isConnected;
};

// Close the socket connection
export const closeSocket = (): void => {
  if (socket) {
    socket.close();
    socket = null;
    lastCollectionId = null;
    lastViewId = null;
    isConnected = false;
    notifyConnectionStatusChange(false);
  }
};

// Create a named object for export
const socketService = {
  initSocket,
  send,
  generateTaskId,
  addMessageListener,
  removeMessageListener,
  addConnectionStatusListener,
  removeConnectionStatusListener,
  getConnectionStatus,
  ensureConnected,
  closeSocket,
};

export default socketService;
