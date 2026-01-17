export const DEFAULT_DQL_QUERY =
  'WITH base_runs AS (\n' +
  '  SELECT id, name, created_at, metadata_json\n' +
  '  FROM agent_runs\n' +
  '  ORDER BY created_at DESC\n' +
  '  LIMIT 20\n' +
  '),\n' +
  'run_metadata AS (\n' +
  '  SELECT\n' +
  '    br.id AS agent_run_id\n' +
  '  FROM base_runs br\n' +
  '),\n' +
  'rubric_results AS (\n' +
  '  SELECT\n' +
  '    jr.agent_run_id,\n' +
  '    jr.rubric_id,\n' +
  '    jr.rubric_version,\n' +
  '    jr.result_type,\n' +
  '    jr.output,\n' +
  '    jr.result_metadata\n' +
  '  FROM judge_results jr\n' +
  '  JOIN base_runs br ON br.id = jr.agent_run_id\n' +
  ')\n' +
  'SELECT\n' +
  '  br.id,\n' +
  '  br.name,\n' +
  '  br.created_at,\n' +
  '  rr.rubric_id,\n' +
  '  rr.rubric_version,\n' +
  '  rr.result_type,\n' +
  '  rr.output,\n' +
  '  rr.result_metadata\n' +
  'FROM base_runs br\n' +
  'LEFT JOIN run_metadata rm ON rm.agent_run_id = br.id\n' +
  'LEFT JOIN rubric_results rr ON rr.agent_run_id = br.id\n' +
  'ORDER BY br.created_at DESC';
