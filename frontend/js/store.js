// Shared app state with a tiny publish/subscribe mechanism.
// The open focus session lives here so every page (and the sidebar) sees the same state,
// whether a change came from this window's buttons or from the live WebSocket.

import { setDisplayTimeZone } from "./dom.js";

const listeners = new Map();

export const store = {
  user: null,
  // The open (active or paused) session, or null when idle.
  session: null,
  // performance.now() when `session` was last received, used to tick the timer locally.
  sessionReceivedAt: 0,
  liveStatus: "connecting",

  on(event, handler) {
    if (!listeners.has(event)) listeners.set(event, new Set());
    listeners.get(event).add(handler);
    return () => listeners.get(event)?.delete(handler);
  },

  emit(event, payload) {
    for (const handler of listeners.get(event) ?? []) handler(payload);
  },

  /** Set the signed-in user (or null). Times across the app follow their timezone. */
  setUser(user) {
    this.user = user;
    setDisplayTimeZone(user?.timezone);
    this.emit("user", user);
  },

  /** Apply a session object from the server (REST response or live event). */
  applySession(session) {
    if (!session) {
      this.setOpenSession(null);
      return;
    }
    if (session.status === "ended") {
      if (this.session?.id === session.id) this.setOpenSession(null);
      this.emit("session-ended", session);
      this.emit("sessions-changed");
      return;
    }
    this.setOpenSession(session);
    this.emit("sessions-changed");
  },

  setOpenSession(session) {
    this.session = session;
    this.sessionReceivedAt = performance.now();
    this.emit("session", session);
  },

  setLiveStatus(status) {
    this.liveStatus = status;
    this.emit("live-status", status);
  },
};

/** Focused seconds right now: the server's value plus time elapsed since we received it (if running). */
export function currentFocusSeconds() {
  const session = store.session;
  if (!session) return 0;
  if (session.status !== "active") return session.duration_seconds;
  return session.duration_seconds + (performance.now() - store.sessionReceivedAt) / 1000;
}

/** Seconds the current pause has lasted. */
export function currentPauseSeconds() {
  const session = store.session;
  if (!session || session.status !== "paused" || !session.paused_at) return 0;
  return Math.max(0, (Date.now() - Date.parse(session.paused_at)) / 1000);
}
