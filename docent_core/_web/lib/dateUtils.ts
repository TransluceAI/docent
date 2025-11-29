export const formatDate = (dateString: string) => {
  const utcString = dateString.endsWith('Z') ? dateString : dateString + 'Z';
  const date = new Date(utcString);
  return date.toLocaleDateString();
};

export const formatDateTime = (dateString: string) => {
  const utcString = dateString.endsWith('Z') ? dateString : dateString + 'Z';
  const date = new Date(utcString);
  return `${date.toLocaleDateString()} ${date.toLocaleTimeString([], {
    hour: '2-digit',
    minute: '2-digit',
  })}`;
};

// NOTE(mengk): I believe the stuff above is deprecated and should be removed.

/**
 * Checks if a value is a valid date string.
 * Only matches ISO 8601 format dates (YYYY-MM-DD or YYYY-MM-DD HH:mm:ss with optional timezone).
 */
export const isDateString = (value: unknown): boolean => {
  if (typeof value !== 'string') {
    return false;
  }
  // Match ISO 8601 format with space separator: YYYY-MM-DD or YYYY-MM-DD HH:mm:ss or YYYY-MM-DD HH:mm:ss.sss
  // This regex ensures we only match proper ISO date strings, not arbitrary text containing dates
  const iso8601Regex = /^\d{4}-\d{2}-\d{2}( \d{2}:\d{2}:\d{2}(\.\d{3,6})?)?$/;

  if (!iso8601Regex.test(value)) {
    return false;
  }

  // Verify it's actually a valid date
  const date = new Date(value);
  return !isNaN(date.getTime());
};

/**
 * Formats a UTC date string using locale-specific formatting.
 * @param dateString - UTC date string (without 'Z' suffix)
 * @param convertToLocal - Whether to convert to local time (default: false, keeps UTC)
 * @returns Formatted date string with UTC offset (e.g., "Jan 15, 2025, 3:45 PM UTC" or "Jan 15, 2025, 3:45 PM UTC-8")
 */
export const formatDateValue = (
  dateString: string,
  convertToLocal: boolean = false
): string => {
  try {
    // dateString is in UTC
    const date = new Date(dateString + 'Z');
    // display in UTC or local time based on parameter
    const formatted = date.toLocaleString('en-US', {
      year: 'numeric',
      month: 'short',
      day: 'numeric',
      hour: 'numeric',
      minute: '2-digit',
      hour12: true,
      timeZone: convertToLocal ? undefined : 'UTC',
    });

    // Add UTC offset indicator
    if (convertToLocal) {
      const offset = -date.getTimezoneOffset() / 60;
      const offsetStr = offset >= 0 ? `+${offset}` : `${offset}`;
      return `${formatted} UTC${offsetStr}`;
    } else {
      return `${formatted} UTC`;
    }
  } catch (error) {
    return dateString;
  }
};
