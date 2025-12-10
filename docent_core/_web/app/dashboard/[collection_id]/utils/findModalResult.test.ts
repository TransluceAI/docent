/// <reference types="bun-types" />

import { describe, expect, test } from 'bun:test';
import type { SchemaDefinition } from '@/app/types/schema';
import type { AgentRunJudgeResults } from '@/app/api/rubricApi';
import type { JudgeResultWithCitations } from '@/app/store/rubricSlice';
import { findModalResult } from './findModalResult';

const createResult = (
  id: string,
  outputValue: string,
  enumKey: string = 'status',
  resultType: JudgeResultWithCitations['result_type'] = 'DIRECT_RESULT'
): JudgeResultWithCitations => ({
  id,
  agent_run_id: 'test-agent-run',
  rubric_id: 'test-rubric',
  rubric_version: 1,
  output: { [enumKey]: outputValue },
  result_type: resultType,
  result_metadata: null,
  _brand: 'citations' as const,
});

const createSchema = (
  enumKey: string,
  enumValues: string[]
): SchemaDefinition => ({
  type: 'object',
  properties: {
    [enumKey]: { type: 'string', enum: enumValues },
  },
});

describe('findMajorityResult', () => {
  test('returns result with most votes', () => {
    const schema = createSchema('status', ['pass', 'fail']);
    const agentRunResult: AgentRunJudgeResults = {
      agent_run_id: 'test-agent-run',
      rubric_id: 'test-rubric',
      rubric_version: 1,
      results: [
        createResult('0', 'fail'),
        createResult('1', 'pass'),
        createResult('2', 'pass'),
        createResult('3', 'pass'),
        createResult('4', 'fail'),
      ],
      reflection: null,
    };

    const result = findModalResult(agentRunResult, schema);

    expect(result.output.status).toBe('pass');
  });

  test('breaks ties by choosing alphabetically first value', () => {
    const schema = createSchema('status', ['pass', 'fail']);
    const agentRunResult: AgentRunJudgeResults = {
      agent_run_id: 'test-agent-run',
      rubric_id: 'test-rubric',
      rubric_version: 1,
      results: [
        createResult('1', 'pass'),
        createResult('2', 'pass'),
        createResult('3', 'fail'),
        createResult('4', 'fail'),
      ],
      reflection: null,
    };

    const result = findModalResult(agentRunResult, schema);

    expect(result.output.status).toBe('fail');
  });

  test('breaks ties with multiple values alphabetically', () => {
    const schema = createSchema('verdict', ['warning', 'pass', 'fail']);
    const agentRunResult: AgentRunJudgeResults = {
      agent_run_id: 'test-agent-run',
      rubric_id: 'test-rubric',
      rubric_version: 1,
      results: [
        createResult('1', 'warning', 'verdict'),
        createResult('2', 'pass', 'verdict'),
        createResult('3', 'fail', 'verdict'),
      ],
      reflection: null,
    };

    const result = findModalResult(agentRunResult, schema);

    expect(result.output.verdict).toBe('fail');
  });

  test('returns first result when schema has no enum property', () => {
    const schema: SchemaDefinition = {
      type: 'object',
      properties: {
        score: { type: 'number', minimum: 0, maximum: 100 },
      },
    };
    const agentRunResult: AgentRunJudgeResults = {
      agent_run_id: 'test-agent-run',
      rubric_id: 'test-rubric',
      rubric_version: 1,
      results: [
        { ...createResult('1', 'pass'), output: { score: 50 } },
        { ...createResult('2', 'pass'), output: { score: 75 } },
      ],
      reflection: null,
    };

    const result = findModalResult(agentRunResult, schema);

    expect(result.id).toBe('1');
    expect(result.output.score).toBe(50);
  });

  test('returns the only result when there is just one', () => {
    const schema = createSchema('status', ['pass', 'fail']);
    const agentRunResult: AgentRunJudgeResults = {
      agent_run_id: 'test-agent-run',
      rubric_id: 'test-rubric',
      rubric_version: 1,
      results: [createResult('1', 'pass')],
      reflection: null,
    };

    const result = findModalResult(agentRunResult, schema);

    expect(result.output.status).toBe('pass');
    expect(result.id).toBe('1');
  });

  test('uses first enum property when multiple exist', () => {
    const schema: SchemaDefinition = {
      type: 'object',
      properties: {
        primary: { type: 'string', enum: ['a', 'b'] },
        secondary: { type: 'string', enum: ['x', 'y'] },
      },
    };
    const agentRunResult: AgentRunJudgeResults = {
      agent_run_id: 'test-agent-run',
      rubric_id: 'test-rubric',
      rubric_version: 1,
      results: [
        {
          ...createResult('1', 'a', 'primary'),
          output: { primary: 'a', secondary: 'x' },
        },
        {
          ...createResult('2', 'a', 'primary'),
          output: { primary: 'a', secondary: 'y' },
        },
        {
          ...createResult('3', 'b', 'primary'),
          output: { primary: 'b', secondary: 'x' },
        },
      ],
      reflection: null,
    };

    const result = findModalResult(agentRunResult, schema);

    expect(result.output.primary).toBe('a');
  });

  test('consistently breaks tie with same values in different order', () => {
    const schema = createSchema('status', ['pass', 'fail']);
    const agentRunResult: AgentRunJudgeResults = {
      agent_run_id: 'test-agent-run',
      rubric_id: 'test-rubric',
      rubric_version: 1,
      results: [
        createResult('1', 'fail'),
        createResult('2', 'fail'),
        createResult('3', 'pass'),
        createResult('4', 'pass'),
      ],
      reflection: null,
    };

    const result = findModalResult(agentRunResult, schema);

    expect(result.output.status).toBe('fail');
  });

  test('ignores failures when selecting modal result', () => {
    const schema = createSchema('status', ['pass', 'fail']);
    const agentRunResult: AgentRunJudgeResults = {
      agent_run_id: 'test-agent-run',
      rubric_id: 'test-rubric',
      rubric_version: 1,
      results: [
        createResult('0', 'fail', 'status', 'FAILURE'),
        createResult('1', 'pass'),
        createResult('2', 'pass'),
      ],
      reflection: null,
    };

    const result = findModalResult(agentRunResult, schema);

    expect(result.id).toBe('1');
    expect(result.output.status).toBe('pass');
  });

  test('handles three-way tie correctly', () => {
    const schema = createSchema('grade', ['A', 'B', 'C']);
    const agentRunResult: AgentRunJudgeResults = {
      agent_run_id: 'test-agent-run',
      rubric_id: 'test-rubric',
      rubric_version: 1,
      results: [
        createResult('1', 'B', 'grade'),
        createResult('2', 'C', 'grade'),
        createResult('3', 'A', 'grade'),
      ],
      reflection: null,
    };

    const result = findModalResult(agentRunResult, schema);

    expect(result.output.grade).toBe('A');
  });
});
