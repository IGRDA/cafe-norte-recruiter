// Entry: read the address once, wire the browser into the effect runner's ports, render.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { App } from "./App";
import "./app.css";
import type { Ports } from "./page/effects";
import { createVoice } from "./voice";

// The store and the opening language come from ?store= and ?lang=. Secrets travel in the
// fragment, which never reaches the server, its logs or a Referer: a private resume link's
// token (#resume=) and the shared access code of a demo link (#code=, D60).
const params = new URLSearchParams(location.search);
const fragment = new URLSearchParams(location.hash.slice(1));
const requested = {
  store: params.get("store"),
  language: params.get("lang") === "en" ? ("en" as const) : ("es" as const),
  resumeToken: fragment.get("resume"),
  code: fragment.get("code"),
};

const ports: Ports = {
  fetch: (...args) => fetch(...args),
  openStream: (url) => new EventSource(url),
  createVoice,
  confirm: (question) => window.confirm(question),
  clearFragment: () => history.replaceState(null, "", location.pathname + location.search),
  navigate: (search) => {
    location.search = search;
  },
  focus: (id) => document.getElementById(id)?.focus(),
  newId: () => crypto.randomUUID(),
};

const root = document.getElementById("root");
if (root) {
  createRoot(root).render(
    <StrictMode>
      <App requested={requested} ports={ports} />
    </StrictMode>,
  );
}
