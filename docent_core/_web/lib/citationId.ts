import { CitationTarget } from '../app/types/citationTypes';

/**
 * Encode a CitationTarget to a URL-safe, valid HTML element ID string.
 *
 * Uses Base64url encoding of minimal JSON to ensure:
 * - Lossless round-trip conversion
 * - Valid HTML element IDs (alphanumeric + _ -)
 * - URL-safe for sharing in hash fragments
 * - Compact representation
 *
 * @param target The citation target to encode
 * @returns A URL-safe string suitable for use as an element ID
 */
export function citationTargetToId(target: CitationTarget): string {
  // Create minimal JSON representation
  const minimalItem: any = {
    t: target.item.item_type,
    a: target.item.agent_run_id,
    c: target.item.collection_id,
  };

  // Add type-specific fields
  switch (target.item.item_type) {
    case 'agent_run_metadata':
      minimalItem.k = target.item.metadata_key;
      break;
    case 'transcript_metadata':
      minimalItem.ti = target.item.transcript_id;
      minimalItem.k = target.item.metadata_key;
      break;
    case 'block_metadata':
      minimalItem.ti = target.item.transcript_id;
      minimalItem.b = target.item.block_idx;
      minimalItem.k = target.item.metadata_key;
      break;
    case 'block_content':
      minimalItem.ti = target.item.transcript_id;
      minimalItem.b = target.item.block_idx;
      break;
  }

  const minimal: any = { i: minimalItem };

  // Add text range if present
  if (target.text_range) {
    minimal.r = {
      s: target.text_range.start_pattern,
      e: target.text_range.end_pattern,
    };
  }

  // Convert to JSON and encode as Base64url
  const json = JSON.stringify(minimal);

  // Handle UTF-8 encoding properly for btoa
  // In browser, btoa only handles ASCII, so we need to encode UTF-8 first
  const utf8Bytes = new TextEncoder().encode(json);
  const binaryString = Array.from(utf8Bytes, (byte) =>
    String.fromCharCode(byte)
  ).join('');
  const base64 = btoa(binaryString);

  // Convert to Base64url format (URL-safe)
  const base64url = base64
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/, '');

  return base64url;
}

/**
 * Decode a citation ID back to a CitationTarget.
 *
 * @param id The encoded citation ID
 * @returns The decoded CitationTarget
 * @throws Error if the ID is invalid or cannot be decoded
 */
export function citationTargetFromId(id: string): CitationTarget {
  try {
    // Convert from Base64url to standard Base64
    let base64 = id.replace(/-/g, '+').replace(/_/g, '/');

    // Add padding if needed
    while (base64.length % 4) {
      base64 += '=';
    }

    // Decode and parse JSON
    // Handle UTF-8 decoding properly from atob
    const binaryString = atob(base64);
    const bytes = new Uint8Array(binaryString.length);
    for (let i = 0; i < binaryString.length; i++) {
      bytes[i] = binaryString.charCodeAt(i);
    }
    const json = new TextDecoder().decode(bytes);
    const minimal = JSON.parse(json);

    // Reconstruct item based on type
    const itemType = minimal.i.t;
    const item: any = {
      item_type: itemType,
      agent_run_id: minimal.i.a,
      collection_id: minimal.i.c,
    };

    // Add type-specific fields
    switch (itemType) {
      case 'agent_run_metadata':
        item.metadata_key = minimal.i.k;
        break;
      case 'transcript_metadata':
        item.transcript_id = minimal.i.ti;
        item.metadata_key = minimal.i.k;
        break;
      case 'block_metadata':
        item.transcript_id = minimal.i.ti;
        item.block_idx = minimal.i.b;
        item.metadata_key = minimal.i.k;
        break;
      case 'block_content':
        item.transcript_id = minimal.i.ti;
        item.block_idx = minimal.i.b;
        break;
      default:
        throw new Error(`Unknown item type: ${itemType}`);
    }

    // Reconstruct text range if present
    const text_range = minimal.r
      ? {
          start_pattern: minimal.r.s,
          end_pattern: minimal.r.e,
        }
      : null;

    return {
      item,
      text_range,
    };
  } catch (error) {
    throw new Error(
      `Failed to decode citation ID: ${error instanceof Error ? error.message : 'unknown error'}`
    );
  }
}
