// Sign in / create account screen.

import { api, setToken } from "../api.js";
import { h, mount } from "../dom.js";

function detectTimezone() {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || "UTC";
  } catch {
    return "UTC";
  }
}

export function renderLogin(root, { onAuthenticated, message }) {
  let mode = "login"; // or "register"

  const email = h("input", { class: "input", type: "email", name: "email", autocomplete: "email", required: true });
  const password = h("input", {
    class: "input",
    type: "password",
    name: "password",
    autocomplete: "current-password",
    required: true,
    minlength: 8,
  });
  const error = h("div", { class: "form-error", role: "alert", hidden: true });
  const submit = h("button", { class: "btn btn-primary btn-block", type: "submit" });
  const title = h("h2", {});
  const switchText = h("span", {});
  const switchButton = h("button", { class: "link-button", type: "button", onclick: toggleMode });

  function showError(text) {
    error.textContent = text;
    error.hidden = !text;
  }

  function render() {
    const registering = mode === "register";
    title.textContent = registering ? "Create your account" : "Welcome back";
    submit.textContent = registering ? "Create account" : "Sign in";
    password.autocomplete = registering ? "new-password" : "current-password";
    switchText.textContent = registering ? "Already have an account? " : "New to FlowSense? ";
    switchButton.textContent = registering ? "Sign in" : "Create an account";
    showError(mode === "login" ? message ?? "" : "");
  }

  function toggleMode() {
    mode = mode === "login" ? "register" : "login";
    message = null;
    render();
  }

  async function handleSubmit(event) {
    event.preventDefault();
    showError("");
    submit.disabled = true;
    const credentials = { email: email.value.trim(), password: password.value };
    try {
      if (mode === "register") {
        await api.post("/auth/register", { ...credentials, timezone: detectTimezone() });
      }
      const { access_token: token } = await api.post("/auth/login", credentials);
      setToken(token);
      onAuthenticated(token, await api.get("/auth/me"));
    } catch (err) {
      showError(err.message);
    } finally {
      submit.disabled = false;
    }
  }

  const form = h(
    "form",
    { class: "stack", onsubmit: handleSubmit, novalidate: true },
    title,
    error,
    h("label", { class: "field" }, h("span", {}, "Email"), email),
    h("label", { class: "field" }, h("span", {}, "Password"), password),
    submit,
    h("p", { class: "auth-switch muted" }, switchText, switchButton),
  );

  mount(
    root,
    h(
      "div",
      { class: "auth" },
      h(
        "div",
        { class: "auth-card" },
        h("div", { class: "brand" }, h("img", { src: "assets/icon.svg", alt: "" }), "FlowSense"),
        h("p", { class: "tagline muted" }, "Deep work, measured."),
        h("div", { class: "card" }, form),
      ),
    ),
  );
  render();
  email.focus();
}
