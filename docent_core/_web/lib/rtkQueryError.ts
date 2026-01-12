type ErrorData =
  | string
  | {
      detail?: string;
      message?: string;
    }
  | null
  | undefined;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

export function getRtkQueryErrorMessage(
  err: unknown,
  fallback: string
): { message: string; status?: number | string } {
  if (!isRecord(err)) return { message: fallback };

  const status =
    'status' in err ? (err.status as number | string | undefined) : undefined;

  if ('data' in err) {
    const data = err.data as ErrorData;
    if (typeof data === 'string' && data.trim()) {
      return { message: data, status };
    }
    if (isRecord(data)) {
      const detail = data.detail;
      if (typeof detail === 'string' && detail.trim()) {
        return { message: detail, status };
      }
      const message = data.message;
      if (typeof message === 'string' && message.trim()) {
        return { message, status };
      }
    }
  }

  if ('error' in err) {
    const error = err.error;
    if (typeof error === 'string' && error.trim()) {
      return { message: error, status };
    }
  }

  if ('message' in err) {
    const message = err.message;
    if (typeof message === 'string' && message.trim()) {
      return { message, status };
    }
  }

  return { message: fallback, status };
}
