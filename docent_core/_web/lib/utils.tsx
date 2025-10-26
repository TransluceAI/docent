import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

export const copyToClipboard = async (text: string) => {
  if (navigator.clipboard) {
    try {
      await navigator.clipboard.writeText(text);
      return true;
    } catch (err) {
      console.log('Clipboard API failed, falling back...');
    }
  }

  // Fallback for non-secure contexts
  const textArea = document.createElement('textarea');
  textArea.value = text;
  textArea.style.position = 'fixed';
  textArea.style.left = '-999999px';
  textArea.style.top = '-999999px';
  document.body.appendChild(textArea);
  textArea.focus();
  textArea.select();

  try {
    document.execCommand('copy');
    return true;
  } catch (err) {
    console.error('Failed to copy text: ', err);
  }

  document.body.removeChild(textArea);
  return false;
};

export const getSchemaPreview = (
  schema: Record<string, any>
): React.ReactNode | string => {
  try {
    const properties = schema?.properties || {};
    if (!properties || typeof properties !== 'object') return '';
    const entries = Object.keys(properties);
    if (entries.length === 0) return '';

    return (
      <>
        {entries.map((key, index) => {
          const property = properties[key];
          const typeStr =
            property.type === 'string' && property.enum
              ? 'enum'
              : property.type;
          return (
            <span key={key}>
              <span className="text-blue-text">{key}</span>
              {': '}
              {typeStr}
              {index < entries.length - 1 && '; '}
            </span>
          );
        })}
      </>
    );
  } catch {
    return '';
  }
};
