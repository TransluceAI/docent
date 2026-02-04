import * as Sentry from '@sentry/nextjs';

Sentry.init({
  dsn: process.env.NEXT_PUBLIC_SENTRY_DSN,
  environment: process.env.NEXT_PUBLIC_SENTRY_ENVIRONMENT || 'development',
  debug: false,

  // Log all server errors to stderr for AWS CloudWatch
  beforeSend(event, hint) {
    const error = hint.originalException;
    const errorInfo = {
      eventId: event.event_id,
      message: error instanceof Error ? error.message : String(error),
      stack: error instanceof Error ? error.stack : undefined,
      url: event.request?.url,
      transaction: event.transaction,
      tags: event.tags,
      timestamp: new Date().toISOString(),
    };
    console.error('[SentryServerError]', JSON.stringify(errorInfo));
    return event;
  },
});
