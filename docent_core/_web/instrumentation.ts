import * as Sentry from '@sentry/nextjs';

export async function register() {
  if (process.env.NEXT_RUNTIME === 'nodejs') {
    await import('./sentry.server.config');

    // Add process-level error handlers for Node.js runtime
    // These catch errors that escape normal error boundaries
    process.on('uncaughtException', async (error) => {
      console.error(
        '[UncaughtException]',
        JSON.stringify({
          message: error.message,
          stack: error.stack,
          timestamp: new Date().toISOString(),
        })
      );
      Sentry.captureException(error);
      // Flush Sentry events before exiting
      await Sentry.close(2000);
      process.exit(1);
    });

    process.on('unhandledRejection', (reason) => {
      const error =
        reason instanceof Error ? reason : new Error(String(reason));
      console.error(
        '[UnhandledRejection]',
        JSON.stringify({
          message: error.message,
          stack: error.stack,
          timestamp: new Date().toISOString(),
        })
      );
      Sentry.captureException(error);
    });
  } else if (process.env.NEXT_RUNTIME === 'edge') {
    await import('./sentry.edge.config');
  }
}

// Note: onRequestError requires Next.js 15+. This project uses Next.js 14,
// so this hook will not be called. Server-side error logging is handled via:
// 1. Sentry's beforeSend hook in sentry.server.config.ts
// 2. Process-level handlers above for uncaught exceptions
// 3. withSentryConfig in next.config.mjs for auto-instrumentation
export const onRequestError = (
  ...args: Parameters<typeof Sentry.captureRequestError>
) => {
  const [error, request, context] = args;
  const err = error instanceof Error ? error : new Error(String(error));
  // Log to stderr for AWS App Runner CloudWatch
  console.error(
    '[ServerError]',
    JSON.stringify({
      message: err.message,
      digest: 'digest' in err ? err.digest : undefined,
      path: request.path,
      method: request.method,
      routerKind: context.routerKind,
      routePath: context.routePath,
      routeType: context.routeType,
      stack: err.stack,
    })
  );
  Sentry.captureRequestError(error, request, context);
};
