import type { AgentRunJudgeResults } from '@/app/api/rubricApi';
import type { JudgeResultWithCitations } from '@/app/store/rubricSlice';
import type { SchemaDefinition } from '@/app/types/schema';

export function findModalResult(
  agentRunResult: AgentRunJudgeResults,
  schema: SchemaDefinition
): JudgeResultWithCitations {
  const results = agentRunResult.results.filter(
    (result) => result.result_type === 'DIRECT_RESULT'
  );
  if (results.length === 0) {
    throw new Error('No judge results available to select a mode from.');
  }

  let firstEnumKey: string | undefined;
  // We're interested in the mode of the first string enum key
  for (const [key, property] of Object.entries(schema.properties)) {
    if (property.type === 'string' && 'enum' in property) {
      firstEnumKey = key;
      break;
    }
  }
  if (!firstEnumKey) {
    return results[0];
  }
  // Count frequencies of each enum value
  const valueCounts: Record<string, number> = {};
  for (const result of results) {
    const value = result.output[firstEnumKey];
    valueCounts[value] = (valueCounts[value] || 0) + 1;
  }
  // Find the mode
  const modalValue = Object.keys(valueCounts).reduce((a, b) => {
    if (valueCounts[a] > valueCounts[b]) return a;
    if (valueCounts[a] < valueCounts[b]) return b;
    // Break ties between enum values alphabetically
    return a < b ? a : b;
  });
  // Return the first result that agrees with the mode
  const majorityResult = results.find(
    (result) => result.output[firstEnumKey] === modalValue
  );
  return majorityResult ?? results[0];
}
