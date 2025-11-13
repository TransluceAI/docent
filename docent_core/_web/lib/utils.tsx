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

const compareLists = (list1: string[], list2: string[]): boolean => {
  if (list1.length !== list2.length) {
    return false;
  }
  for (const item of list1) {
    if (!list2.includes(item)) {
      return false;
    }
  }
  return true;
};

/**
 * Deep comparison of two JSON schemas to check if they are compatible.
 * Performs strict comparison: all constraints must match exactly.
 *
 * @param schema1 First schema to compare
 * @param schema2 Second schema to compare
 * @returns true if schemas are compatible, false otherwise
 */
export const areSchemasCompatible = (
  schema1: Record<string, any>,
  schema2: Record<string, any>
): boolean => {
  // Compare required arrays (order-independent)
  const required1 = schema1.required || [];
  const required2 = schema2.required || [];
  if (!compareLists(required1, required2)) {
    return false;
  }

  // Get properties from both schemas
  const props1 = schema1.properties || {};
  const props2 = schema2.properties || {};

  // Must have the same set of properties (order doesn't matter)
  const keys1 = Object.keys(props1);
  const keys2 = Object.keys(props2);
  if (!compareLists(keys1, keys2)) {
    return false;
  }

  // Compare each property
  for (const key of keys1) {
    const prop1 = props1[key];
    const prop2 = props2[key];

    // Type must match exactly
    if (prop1.type !== prop2.type) {
      return false;
    }

    // Format must match if present in either
    if ('format' in prop1 || 'format' in prop2) {
      if (prop1.format !== prop2.format) {
        return false;
      }
    }

    // Enum must have same values (order doesn't matter)
    if ('enum' in prop1 || 'enum' in prop2) {
      if (!('enum' in prop1) || !('enum' in prop2)) {
        return false;
      }
      const enum1Set = new Set(prop1.enum);
      const enum2Set = new Set(prop2.enum);
      if (enum1Set.size !== enum2Set.size) {
        return false;
      }
      for (const val of prop1.enum) {
        if (!enum2Set.has(val)) {
          return false;
        }
      }
    }

    // Numeric constraints must match if present in either
    const numericConstraints = [
      'minimum',
      'maximum',
      'exclusiveMinimum',
      'exclusiveMaximum',
      'multipleOf',
    ];
    for (const constraint of numericConstraints) {
      if (constraint in prop1 || constraint in prop2) {
        if (prop1[constraint] !== prop2[constraint]) {
          return false;
        }
      }
    }

    // String constraints and other property constraints must match if present in either
    const stringConstraints = [
      'minLength',
      'maxLength',
      'pattern',
      'citations',
    ];
    for (const constraint of stringConstraints) {
      if (constraint in prop1 || constraint in prop2) {
        if (prop1[constraint] !== prop2[constraint]) {
          return false;
        }
      }
    }
  }

  return true;
};
