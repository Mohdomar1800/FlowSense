// WebSocket connection for live updates, with automatic reconnect (exponential backoff).

import { getToken } from "./api.js";

const PING_INTERVAL_MS = 25_000;
const MAX_BACKOFF_MS = 30_000;
const UNAUTHORIZED_CLOSE_CODE = 4401;

/**
 * connectLive({ onMessage, onStatus, onUnauthorized }) -> { close() }
 * onStatus receives "connecting" | "online" | "offline".
 */
export function connectLive({ onMessage, onStatus = () => {}, onUnauthorized = () => {} }) {
  let socket = null;
  let attempt = 0;
  let pingTimer = null;
  let retryTimer = null;
  let closed = false;

  function open() {
    onStatus("connecting");
    const protocol = location.protocol === "https:" ? "wss" : "ws";
    const token = encodeURIComponent(getToken() ?? "");
    socket = new WebSocket(`${protocol}://${location.host}/api/v1/ws?token=${token}`);

    socket.addEventListener("open", () => {
      attempt = 0;
      onStatus("online");
      pingTimer = setInterval(() => socket.readyState === WebSocket.OPEN && socket.send("ping"), PING_INTERVAL_MS);
    });

    socket.addEventListener("message", (event) => {
      if (event.data === "pong") return;
      try {
        onMessage(JSON.parse(event.data));
      } catch (error) {
        console.error("Bad live message", error);
      }
    });

    socket.addEventListener("close", (event) => {
      clearInterval(pingTimer);
      if (closed) return;
      if (event.code === UNAUTHORIZED_CLOSE_CODE) {
        onUnauthorized();
        return;
      }
      onStatus("offline");
      const delay = Math.min(MAX_BACKOFF_MS, 1000 * 2 ** attempt++);
      retryTimer = setTimeout(open, delay);
    });
  }

  open();
  return {
    close() {
      closed = true;
      clearInterval(pingTimer);
      clearTimeout(retryTimer);
      socket?.close();
    },
  };
}
