// Describe why a Grafana /api/ds/query response failed, or return null when every query succeeded.
// A non-2xx status fails outright; a 2xx (including 207 Multi-Status) can still carry per-query errors.
export async function queryFailure(response) {
  if (!response.ok()) return `HTTP ${response.status()}`;
  const body = await response.json().catch(() => null);
  if (!body || typeof body !== 'object') return 'response is not JSON';
  const failed = Object.entries(body.results ?? {}).filter(([, result]) => result?.error);
  return failed.length ? failed.map(([refId, result]) => `${refId}: ${result.error}`).join('; ') : null;
}
