const API = "/api";
const IDENTITY_KEY = "insights.sso-stub";

export interface HeadcountRecord {
  team: string;
  month: string;
  count: number;
}

// SSO stub for the browser: in production the SSO proxy sets the X-Insights-* headers and this
// identity is never consulted. Here the sign-in form stores it for the session and the client
// sends it on every request, the same way the Vite dev proxy does from .env.local.
export interface Identity {
  user: string;
  team: string;
  roles: string;
}

export function getIdentity(): Identity | null {
  const raw = sessionStorage.getItem(IDENTITY_KEY);
  return raw === null ? null : (JSON.parse(raw) as Identity);
}

export function setIdentity(identity: Identity): void {
  sessionStorage.setItem(IDENTITY_KEY, JSON.stringify(identity));
}

export function clearIdentity(): void {
  sessionStorage.removeItem(IDENTITY_KEY);
}

function identityHeaders(): Record<string, string> {
  const identity = getIdentity();
  if (identity === null) {
    return {};
  }
  const headers: Record<string, string> = {
    "X-Insights-User": identity.user,
    "X-Insights-Team": identity.team,
  };
  if (identity.roles) {
    headers["X-Insights-Roles"] = identity.roles;
  }
  return headers;
}

async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${API}${path}`, {
    headers: { Accept: "application/json", ...identityHeaders() },
  });
  if (!response.ok) {
    throw new Error(`GET ${API}${path} failed with ${response.status}`);
  }
  return (await response.json()) as T;
}

export function fetchRecords(): Promise<HeadcountRecord[]> {
  return getJson<HeadcountRecord[]>("/records");
}
