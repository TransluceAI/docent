import { toast } from '@/hooks/use-toast';

/**
 * Handle RTK Query errors consistently across the investigator frontend
 */
export function handleInvestigatorError(
  error: any,
  defaultMessage: string = 'An error occurred'
) {
  const errorObj = error as any;

  // Handle 403 specifically
  if (errorObj?.status === 403) {
    toast({
      title: 'Access Denied',
      description:
        'You are not authorized to perform this action in the investigator.',
      variant: 'destructive',
    });
    return;
  }

  // Handle validation errors (FastAPI returns these as arrays)
  let message = defaultMessage;

  if (errorObj?.data?.detail) {
    if (Array.isArray(errorObj.data.detail)) {
      // Format validation errors from FastAPI
      const errors = errorObj.data.detail.map((err: any) => {
        const field = err.loc?.join('.') || 'field';
        return `${field}: ${err.msg}`;
      });
      message = errors.join(', ');
    } else if (typeof errorObj.data.detail === 'string') {
      message = errorObj.data.detail;
    } else if (typeof errorObj.data.detail === 'object') {
      // Try to stringify the object if it's not a string or array
      message = JSON.stringify(errorObj.data.detail);
    }
  } else if (errorObj?.message) {
    message = errorObj.message;
  }

  toast({
    title: 'Error',
    description: message,
    variant: 'destructive',
  });
}

/**
 * Check if an error is a 403 Forbidden error
 */
export function is403Error(error: any): boolean {
  return error?.status === 403;
}

/**
 * Get a user-friendly error message from an RTK Query error
 */
export function getErrorMessage(
  error: any,
  defaultMessage: string = 'An error occurred'
): string {
  const errorObj = error as any;

  if (errorObj?.status === 403) {
    return 'Access denied: You are not authorized for investigator features';
  }

  return errorObj?.data?.detail || errorObj?.message || defaultMessage;
}
