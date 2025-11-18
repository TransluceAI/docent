/// <reference types="bun-types" />

import { describe, expect, test } from 'bun:test';
import { citationTargetToId, citationTargetFromId } from './citationId';
import type { CitationTarget } from '../app/types/citationTypes';

describe('citationTargetToId', () => {
  test('encodes agent_run_metadata without text range', () => {
    const target: CitationTarget = {
      item: {
        item_type: 'agent_run_metadata',
        agent_run_id: 'run-123',
        collection_id: 'coll-456',
        metadata_key: 'test_key',
      },
      text_range: null,
    };

    const encoded = citationTargetToId(target);
    const decoded = citationTargetFromId(encoded);

    expect(decoded.item.item_type).toBe('agent_run_metadata');
    expect(decoded.item.agent_run_id).toBe('run-123');
    expect(decoded.item.collection_id).toBe('coll-456');
    if (decoded.item.item_type === 'agent_run_metadata') {
      expect(decoded.item.metadata_key).toBe('test_key');
    }
    expect(decoded.text_range).toBeNull();
  });

  test('encodes agent_run_metadata with text range', () => {
    const target: CitationTarget = {
      item: {
        item_type: 'agent_run_metadata',
        agent_run_id: 'run-123',
        collection_id: 'coll-456',
        metadata_key: 'test_key',
      },
      text_range: {
        start_pattern: 'hello world',
        end_pattern: null,
      },
    };

    const encoded = citationTargetToId(target);
    const decoded = citationTargetFromId(encoded);

    expect(decoded.item.item_type).toBe('agent_run_metadata');
    expect(decoded.text_range).not.toBeNull();
    expect(decoded.text_range?.start_pattern).toBe('hello world');
    expect(decoded.text_range?.end_pattern).toBeNull();
  });

  test('encodes transcript_metadata', () => {
    const target: CitationTarget = {
      item: {
        item_type: 'transcript_metadata',
        agent_run_id: 'run-123',
        collection_id: 'coll-456',
        transcript_id: 'trans-789',
        metadata_key: 'test_key',
      },
      text_range: null,
    };

    const encoded = citationTargetToId(target);
    const decoded = citationTargetFromId(encoded);

    expect(decoded.item.item_type).toBe('transcript_metadata');
    expect(decoded.item.agent_run_id).toBe('run-123');
    expect(decoded.item.collection_id).toBe('coll-456');
    if (decoded.item.item_type === 'transcript_metadata') {
      expect(decoded.item.transcript_id).toBe('trans-789');
      expect(decoded.item.metadata_key).toBe('test_key');
    }
  });

  test('encodes block_metadata', () => {
    const target: CitationTarget = {
      item: {
        item_type: 'block_metadata',
        agent_run_id: 'run-123',
        collection_id: 'coll-456',
        transcript_id: 'trans-789',
        block_idx: 42,
        metadata_key: 'test_key',
      },
      text_range: null,
    };

    const encoded = citationTargetToId(target);
    const decoded = citationTargetFromId(encoded);

    expect(decoded.item.item_type).toBe('block_metadata');
    expect(decoded.item.agent_run_id).toBe('run-123');
    expect(decoded.item.collection_id).toBe('coll-456');
    if (decoded.item.item_type === 'block_metadata') {
      expect(decoded.item.transcript_id).toBe('trans-789');
      expect(decoded.item.block_idx).toBe(42);
      expect(decoded.item.metadata_key).toBe('test_key');
    }
  });

  test('encodes block_content without text range', () => {
    const target: CitationTarget = {
      item: {
        item_type: 'block_content',
        agent_run_id: 'run-123',
        collection_id: 'coll-456',
        transcript_id: 'trans-789',
        block_idx: 42,
      },
      text_range: null,
    };

    const encoded = citationTargetToId(target);
    const decoded = citationTargetFromId(encoded);

    expect(decoded.item.item_type).toBe('block_content');
    expect(decoded.item.agent_run_id).toBe('run-123');
    expect(decoded.item.collection_id).toBe('coll-456');
    if (decoded.item.item_type === 'block_content') {
      expect(decoded.item.transcript_id).toBe('trans-789');
      expect(decoded.item.block_idx).toBe(42);
    }
    expect(decoded.text_range).toBeNull();
  });

  test('encodes block_content with text range', () => {
    const target: CitationTarget = {
      item: {
        item_type: 'block_content',
        agent_run_id: 'run-123',
        collection_id: 'coll-456',
        transcript_id: 'trans-789',
        block_idx: 42,
      },
      text_range: {
        start_pattern: 'hello world',
        end_pattern: 'goodbye',
      },
    };

    const encoded = citationTargetToId(target);
    const decoded = citationTargetFromId(encoded);

    expect(decoded.item.item_type).toBe('block_content');
    expect(decoded.item.agent_run_id).toBe('run-123');
    expect(decoded.item.collection_id).toBe('coll-456');
    if (decoded.item.item_type === 'block_content') {
      expect(decoded.item.transcript_id).toBe('trans-789');
      expect(decoded.item.block_idx).toBe(42);
    }
    expect(decoded.text_range).not.toBeNull();
    expect(decoded.text_range?.start_pattern).toBe('hello world');
    expect(decoded.text_range?.end_pattern).toBe('goodbye');
  });

  test('encoded ID is URL-safe', () => {
    const target: CitationTarget = {
      item: {
        item_type: 'block_content',
        agent_run_id: 'run-123',
        collection_id: 'coll-456',
        transcript_id: 'trans-789',
        block_idx: 42,
      },
      text_range: {
        start_pattern: 'hello world with special chars: !@#$%^&*()',
        end_pattern: null,
      },
    };

    const encoded = citationTargetToId(target);

    // Base64url should only contain alphanumeric, -, and _
    const urlSafeRegex = /^[A-Za-z0-9_-]+$/;
    expect(urlSafeRegex.test(encoded)).toBe(true);
  });

  test('encoded ID is valid HTML element ID', () => {
    const target: CitationTarget = {
      item: {
        item_type: 'block_content',
        agent_run_id: 'run-123',
        collection_id: 'coll-456',
        transcript_id: 'trans-789',
        block_idx: 42,
      },
      text_range: {
        start_pattern: 'text with spaces and unicode: café 日本語',
        end_pattern: null,
      },
    };

    const encoded = citationTargetToId(target);

    // HTML element IDs should not contain spaces or most special characters
    expect(encoded).not.toContain(' ');
    const validIdRegex = /^[A-Za-z0-9_-]+$/;
    expect(validIdRegex.test(encoded)).toBe(true);
  });

  test('throws error for invalid ID', () => {
    expect(() => {
      citationTargetFromId('invalid-not-base64!!!');
    }).toThrow('Failed to decode citation ID');
  });

  test('handles text range with null values', () => {
    const target: CitationTarget = {
      item: {
        item_type: 'block_content',
        agent_run_id: 'run-123',
        collection_id: 'coll-456',
        transcript_id: 'trans-789',
        block_idx: 42,
      },
      text_range: {
        start_pattern: null,
        end_pattern: null,
      },
    };

    const encoded = citationTargetToId(target);
    const decoded = citationTargetFromId(encoded);

    expect(decoded.text_range).not.toBeNull();
    expect(decoded.text_range?.start_pattern).toBeNull();
    expect(decoded.text_range?.end_pattern).toBeNull();
  });

  test('round-trip with complex unicode', () => {
    const target: CitationTarget = {
      item: {
        item_type: 'agent_run_metadata',
        agent_run_id: 'run-123',
        collection_id: 'coll-456',
        metadata_key: 'test_key',
      },
      text_range: {
        start_pattern: 'emoji: 😀🎉🔥 chinese: 你好 arabic: مرحبا',
        end_pattern: 'more unicode: ñ ü ö',
      },
    };

    const encoded = citationTargetToId(target);
    const decoded = citationTargetFromId(encoded);

    expect(decoded.text_range).not.toBeNull();
    expect(decoded.text_range?.start_pattern).toBe(
      'emoji: 😀🎉🔥 chinese: 你好 arabic: مرحبا'
    );
    expect(decoded.text_range?.end_pattern).toBe('more unicode: ñ ü ö');
  });

  test('handles long UUIDs', () => {
    const target: CitationTarget = {
      item: {
        item_type: 'block_content',
        agent_run_id: '550e8400-e29b-41d4-a716-446655440000',
        collection_id: '6ba7b810-9dad-11d1-80b4-00c04fd430c8',
        transcript_id: '7c9e6679-7425-40de-944b-e07fc1f90ae7',
        block_idx: 999,
      },
      text_range: {
        start_pattern:
          'This is a very long citation pattern that might appear in actual usage',
        end_pattern: 'And this is the end pattern',
      },
    };

    const encoded = citationTargetToId(target);
    const decoded = citationTargetFromId(encoded);

    expect(decoded.item.agent_run_id).toBe(
      '550e8400-e29b-41d4-a716-446655440000'
    );
    expect(decoded.item.collection_id).toBe(
      '6ba7b810-9dad-11d1-80b4-00c04fd430c8'
    );
    if (decoded.item.item_type === 'block_content') {
      expect(decoded.item.transcript_id).toBe(
        '7c9e6679-7425-40de-944b-e07fc1f90ae7'
      );
      expect(decoded.item.block_idx).toBe(999);
    }
  });
});
