// Validates GRAFANA_URL for the pinned-certificate capture proxy and returns it without a trailing slash.
// With a Microsoft Entra token (Azure Managed Grafana) the endpoint has a public certificate, so the
// default trust store is used instead of a pinned gateway certificate.
export function grafanaBase(value, caFile, { token = false } = {}) {
  const base = value?.replace(/\/$/, '');
  if (!base || !base.startsWith('https://') || (!caFile && !token)) {
    throw new Error('GRAFANA_URL must be https and GRAFANA_CA_FILE must pin the gateway certificate');
  }
  // The loopback proxy forwards request paths as they are, so Grafana must be served at the root;
  // a sub-path would send the login form to another service on the same host.
  const url = new URL(base);
  if (url.pathname !== '/' || url.search || url.hash) {
    throw new Error('GRAFANA_URL must be the Grafana root (https://host:port) without a path, query or fragment');
  }
  return base;
}
