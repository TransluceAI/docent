'use client';

import * as Sentry from '@sentry/nextjs';
import { useEffect } from 'react';

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    // Log structured error info to browser console
    console.error(
      '[GlobalError]',
      JSON.stringify({
        message: error.message,
        digest: error.digest,
        name: error.name,
        timestamp: new Date().toISOString(),
      })
    );
    console.error('[GlobalError Stack]', error.stack);

    // Capture to Sentry with additional context
    Sentry.captureException(error, {
      tags: {
        errorBoundary: 'global',
        digest: error.digest,
      },
    });
  }, [error]);

  return (
    <html lang="en">
      <body>
        <div
          style={{
            padding: '2rem',
            fontFamily: 'system-ui',
            maxWidth: '600px',
            margin: '0 auto',
          }}
        >
          <h2 style={{ marginBottom: '1rem' }}>Something went wrong</h2>
          <p style={{ color: '#666', marginBottom: '1rem' }}>
            An unexpected error occurred. Our team has been notified.
          </p>
          {error.digest && (
            <p
              style={{
                fontSize: '0.875rem',
                color: '#999',
                marginBottom: '1rem',
              }}
            >
              Error ID: {error.digest}
            </p>
          )}
          <button
            onClick={reset}
            style={{
              padding: '0.5rem 1rem',
              backgroundColor: '#0070f3',
              color: 'white',
              border: 'none',
              borderRadius: '4px',
              cursor: 'pointer',
            }}
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  );
}
