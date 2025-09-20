import { BASE_URL } from '../constants';
import { v4 as uuidv4 } from 'uuid';
import { setToastNotification } from '../store/toastSlice';

// Map to store active EventSource instances
const eventSourcesMap: Record<string, EventSource> = {};

/**
 * Generate a unique task ID for SSE requests
 */
const generateTaskId = (): string => {
  return uuidv4();
};

/**
 * Create and return an SSE connection with handlers for events
 * @param url The URL to connect to (must start with a leading slash)
 * @param onMessage Function to handle incoming messages
 * @param onFinish Function called when the connection is closed
 * @param dispatch Redux dispatch function for error handling
 * @returns An object containing the EventSource and a function to cancel the connection
 */
const createEventSource = (
  url: string,
  onMessage: (data: any) => void,
  onFinish: () => void,
  dispatch: (action: any) => void // Add dispatch parameter
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
      onMessage(data);
    } catch (error) {
      console.error('Error parsing SSE data:', error);
      dispatch(
        setToastNotification({
          title: 'Error parsing data',
          description: 'Failed to parse server-sent event data',
          variant: 'destructive',
        })
      );
    }
  };

  // Define the error handler
  eventSource.onerror = (error) => {
    console.error('EventSource error:', error);
    // dispatch(
    //   setToastNotification({
    //     title: 'Connection error',
    //     description: 'Server-sent event connection failed',
    //     variant: 'destructive',
    //   })
    // );
    // closeConnection();
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

/**
 * SSE doesn't work with POST; this provides similar functionality for
 * run uploads with progress updates
 */
function postEventStream(
  url: string,
  body: FormData,
  onMessage: (data: any) => void,
  onFinish: () => void,
  dispatch: (action: any) => void
): { onCancel: () => void } {
  const taskId = generateTaskId();

  const controller = new AbortController();

  let cancelled = false;

  const closeConnection = () => {
    cancelled = true;
    controller.abort();
    delete eventSourcesMap[taskId];
    onFinish();
  };

  // Store a dummy reference so we can reuse the same cleanup map
  // (keeps a single place to cancel ongoing streams by taskId if needed)
  eventSourcesMap[taskId] = {
    close: closeConnection,
  } as unknown as EventSource;

  // Kick off the POST request and parse the response stream
  (async () => {
    try {
      const response = await fetch(`${BASE_URL}${url}`, {
        method: 'POST',
        body,
        credentials: 'include',
        signal: controller.signal,
      });

      if (!response.ok || !response.body) {
        throw new Error(`Stream request failed with status ${response.status}`);
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = '';

      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split('\n\n');
        buffer = parts.pop() ?? '';

        for (const part of parts) {
          const lines = part.split('\n');
          for (const line of lines) {
            if (!line.startsWith('data: ')) continue;
            const payloadText = line.slice(6);
            if (payloadText === '[DONE]') {
              closeConnection();
              return;
            }
            try {
              const data = JSON.parse(payloadText);
              onMessage(data);
            } catch (error) {
              console.error('Error parsing SSE POST data:', error);
              dispatch(
                setToastNotification({
                  title: 'Error parsing data',
                  description: 'Failed to parse server-sent event data',
                  variant: 'destructive',
                })
              );
            }
          }
        }
      }
    } catch (error) {
      if (!cancelled) {
        console.error('POST event stream error:', error);
        dispatch(
          setToastNotification({
            title: 'Connection error',
            description: 'Server-sent event connection failed',
            variant: 'destructive',
          })
        );
      }
    } finally {
      closeConnection();
    }
  })();

  return { onCancel: closeConnection };
}
const sseService = {
  createEventSource,
  generateTaskId,
  postEventStream,
};

export default sseService;
