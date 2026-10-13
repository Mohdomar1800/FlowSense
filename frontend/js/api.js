// HTTP client for the FlowSense API (same origin, so no CORS and no hardcoded host).

const BASE = "/api/v1";
const TOKEN_KEY = "flowsense.token";

let memoryToken = null; // fallback when storage is unavailable (private mode, blocked storage)
let unauthorizedHandler = () => {};

export class ApiError extends Error {
  constructor(status, type, message, details = null) {
    super(message);
    this.status = status;
    this.type = type;
    this.details = details;
  }
}

export function getToken() {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? memoryToken;
  } catch {
    return memoryToken;
  }
}

export function setToken(token) {
  memoryToken = token;
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage blocked: keep the in-memory copy */
  }
}

/** Called when the server rejects our token (expired or revoked). */
export function onUnauthorized(handler) {
  unauthorizedHandler = handler;
}

function describeValidationError(details) {
  if (!Array.isArray(details) || details.length === 0) return "Please check the form and try again.";
  return details
    .map((d) => {
      const field = d.loc?.filter((part) => part !== "body").join(".");
      const message = String(d.msg ?? "is invalid").replace(/^Value error, /, "");
      return field ? `${field}: ${message}` : message;
    })
    .join("\n");
}

async function request(method, path, body) {
  const token = getToken();
  const headers = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  if (token) headers.Authorization = `Bearer ${token}`;

  let response;
  try {
    response = await fetch(BASE + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "Can't reach the FlowSense server. Is it running?");
  }

  if (response.status === 204) return null;
  const data = await response.json().catch(() => null);
  if (response.ok) return data;

  const error = data?.error ?? {};
  if (response.status === 401 && token) unauthorizedHandler();
  const message =
    error.type === "validation_error" ? describeValidationError(error.details) : error.message || `Request failed (${response.status})`;
  throw new ApiError(response.status, error.type ?? "error", message, error.details ?? null);
}

export const api = {
  request,
  get: (path) => request("GET", path),
  post: (path, body = {}) => request("POST", path, body),
  patch: (path, body) => request("PATCH", path, body),
  delete: (path) => request("DELETE", path),
};

/** Build a query string, skipping empty values. */
export function query(params) {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== null && value !== undefined && value !== "") search.set(key, value);
  }
  const text = search.toString();
  return text ? `?${text}` : "";
}
