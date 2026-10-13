// Bridge to the native desktop app (pywebview). In a normal browser these are no-ops.

function bridge() {
  return window.pywebview?.api ?? null;
}

/** Resolves once the desktop bridge is ready, or with null after `timeoutMs` (plain browser). */
function whenReady(timeoutMs = 3000) {
  if (bridge()) return Promise.resolve(bridge());
  return new Promise((resolve) => {
    const timer = setTimeout(() => resolve(null), timeoutMs);
    window.addEventListener(
      "pywebviewready",
      () => {
        clearTimeout(timer);
        resolve(bridge());
      },
      { once: true },
    );
  });
}

export function isDesktopApp() {
  return Boolean(bridge()) || "pywebview" in window;
}

/** { config_file, log_dir } from the desktop app, or null in a plain browser. */
export async function getDesktopInfo() {
  const api = await whenReady(1000);
  if (!api?.info) return null;
  try {
    return await api.info();
  } catch {
    return null;
  }
}

/** { available, in_use } for the desktop app's camera, or null in a plain browser. */
export async function getCameraStatus() {
  const api = bridge();
  if (!api?.camera_status) return null;
  try {
    return await api.camera_status();
  } catch {
    return null;
  }
}

/** Give the desktop agent the signed-in user's token (null on sign-out), so it can track the screen. */
export async function syncAgentToken(token) {
  const api = await whenReady();
  if (!api) return;
  try {
    await api.set_token(token ?? null);
  } catch (error) {
    console.warn("Desktop agent unavailable", error);
  }
}
