export const DEFAULT_DQL_QUERY = `SELECT
  id,
  name,
  created_at
FROM agent_runs
ORDER BY created_at DESC
LIMIT 20`;
