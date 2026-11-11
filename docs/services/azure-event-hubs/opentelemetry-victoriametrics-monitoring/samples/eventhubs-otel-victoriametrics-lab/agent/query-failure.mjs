// Describe why a Grafana /api/ds/query response failed, or return null when every query succeeded.
// A non-2xx status fails outright; a 2xx (including 207 Multi-Status) can still carry per-query errors.
export async function queryFailure(response) {
  if (!response.ok()) return `HTTP ${response.status()}`;
  const body = await response.json().catch(() => null);
  if (!body || typeof body !== 'object') return 'response is not JSON';
  const { results } = body;
  // Every capture request carries at least one query, so no results is a failure, not a success.
  if (!results || typeof results !== 'object' || Array.isArray(results) || !Object.keys(results).length) {
    return 'response has no query results';
  }
  const failed = Object.entries(results).filter(([, result]) => result?.error);
  return failed.length ? failed.map(([refId, result]) => `${refId}: ${result.error}`).join('; ') : null;
}
