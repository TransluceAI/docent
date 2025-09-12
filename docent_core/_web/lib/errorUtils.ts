import * as Sentry from '@sentry/nextjs';
import { toast } from '@/hooks/use-toast';

interface ErrorToastOptions {
  title: string;
  description?: string;
  variant?: 'default' | 'destructive';
  context?: Record<string, any>;
}

/**
 * Shows a toast notification and logs the error to Sentry if available.
 * Fails gracefully if Sentry is not properly configured.
 */
export function logErrorWithToast(
  error: Error | string,
  options: ErrorToastOptions
) {
  const errorObj = typeof error === 'string' ? new Error(error) : error;

  // Always log to console
  console.error(errorObj.message);

  const sentryOptions = options.context
    ? { contexts: { error_context: options.context } }
    : undefined;
  Sentry.captureException(errorObj, sentryOptions);

  // Show toast notification
  toast({
    title: options.title,
    description: options.description,
    variant: options.variant || 'destructive',
  });
}
