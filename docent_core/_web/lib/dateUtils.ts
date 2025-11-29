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
 */
export const isDateString = (value: unknown): boolean => {
  if (typeof value !== 'string') {
    return false;
  }
  // Check if it's an ISO date string or other common date formats
  const date = new Date(value);
  return !isNaN(date.getTime()) && value.length > 8; // Ensure it's not just a number
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
