import { BASE_URL } from '../constants';

// Map to store active EventSource instances
const eventSourcesMap: Record<string, EventSource> = {};

/**
 * Generate a unique task ID for SSE requests
 */
const generateTaskId = (): string => {
  return `sse-${Date.now()}-${Math.random().toString(36).substring(2, 10)}`;
};

/**
 * Create and return an SSE connection with handlers for events
 * @param url The URL to connect to (must start with a leading slash)
 * @param onMessage Function to handle incoming messages
 * @param onFinish Function called when the connection is closed
 * @returns An object containing the EventSource and a function to cancel the connection
 */
const createEventSource = (
  url: string,
  onMessage: (data: any) => void,
  onFinish: () => void,
  onToast: (
    title: string,
    description: string,
    variant: 'default' | 'destructive'
  ) => void
): { eventSource: EventSource; onCancel: () => void } => {
  // Generate a unique task ID
  const taskId = generateTaskId();

  // Create the EventSource - caller must include leading slash in URL
  const eventSource = new EventSource(`${BASE_URL}${url}`, {
    withCredentials: true,
  });

  // Store the EventSource reference for cleanup
  eventSourcesMap[taskId] = eventSource;

  // Define the message handler
  eventSource.onmessage = (event) => {
    if (event.data === '[DONE]') {
      closeConnection();
      return;
    }

    try {
      const data = JSON.parse(event.data);
      console.log('(sse)', data);
      onMessage(data);
    } catch (error) {
      console.error('Error parsing SSE data:', error);
      onToast(
        'Error parsing data',
        'Failed to parse server-sent event data',
        'destructive'
      );
    }
  };

  // Define the error handler
  eventSource.onerror = (error) => {
    console.error('EventSource error:', error);
    onToast(
      'Connection error',
      'Server-sent event connection failed',
      'destructive'
    );
    closeConnection();
  };

  // Function to close the connection and clean up
  const closeConnection = () => {
    if (eventSourcesMap[taskId]) {
      eventSource.close();
      delete eventSourcesMap[taskId];
    }
    onFinish();
  };

  // Return the event source and a function to cancel it
  return {
    eventSource,
    onCancel: closeConnection,
  };
};

const sseService = {
  createEventSource,
  generateTaskId,
};

export default sseService;
