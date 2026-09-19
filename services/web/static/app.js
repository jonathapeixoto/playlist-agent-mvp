"use strict";

const log = document.getElementById("chat-log");
const form = document.getElementById("composer");
const input = document.getElementById("text");
const preview = document.getElementById("preview");
const statusEl = document.getElementById("status");
const loginLink = document.getElementById("login");

// Cria elementos só com textContent: títulos de música vêm de fora e nunca viram HTML.
function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "onclick") node.addEventListener("click", value);
    else if (key === "class") node.className = value;
    else node.setAttribute(key, value);
  }
  for (const child of children) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}

async function api(path, body) {
  const options = body === undefined
    ? {}
    : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
  const response = await fetch(path, options);
  const data = await response.json().catch(() => ({}));
  if (response.status === 401) {
    loginLink.hidden = false;
    throw new Error(data.detail || "Faça login no Spotify para continuar.");
  }
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : `Erro ${response.status}`);
  return data;
}

function say(role, text) {
  const node = el("div", { class: `msg ${role}` }, text);
  log.append(node);
  log.scrollTop = log.scrollHeight;
  return node;
}

function setBusy(busy) {
  document.body.classList.toggle("busy", busy);
  for (const control of document.querySelectorAll("button, input")) control.disabled = busy;
}

async function run(waitText, call) {
  setBusy(true);
  const pending = say("agent pending", waitText);
  try {
    render(await call());
  } catch (error) {
    say("error", error.message);
  } finally {
    pending.remove();
    setBusy(false);
    input.focus();
  }
}

function render(reply) {
  say("agent", reply.message);
  if (reply.options && reply.options.length) renderOptions(reply.options);
  if (reply.plan) renderPlan(reply.plan);
  if (reply.result) renderResult(reply.result);
}

function renderOptions(options) {
  const box = el("div", { class: "options" });
  options.forEach((option, index) => {
    const pick = () => {
      box.remove();
      say("user", option.label);
      run("Montando a prévia: lendo músicas, buscando BPM e gênero...", () => api("/api/choose", { index }));
    };
    box.append(el("button", { type: "button", onclick: pick }, el("strong", {}, option.label), el("span", {}, option.description)));
  });
  log.append(box);
  log.scrollTop = log.scrollHeight;
}

const pct = (value) => `${Math.round(value * 100)}%`;

function trackRow(item, index, previous) {
  const before = previous === undefined ? "" : previous === null ? "novo" : String(previous + 1);
  return el("tr", {},
    el("td", {}, index + 1),
    el("td", {}, item.track.name),
    el("td", {}, item.track.artists.map((a) => a.name).join(", ")),
    el("td", { class: item.tempo ? "" : "missing" }, item.tempo ? Math.round(item.tempo) : "sem BPM"),
    el("td", { class: item.genres.length ? "" : "missing" }, item.genres[0] || "sem gênero"),
    el("td", {}, before));
}

function renderPlan(plan) {
  preview.replaceChildren(
    el("h2", {}, "Prévia"),
    el("p", { class: "meta" }, `BPM em ${pct(plan.bpm_coverage)} das faixas · gênero em ${pct(plan.genre_coverage)}`));
  for (const playlist of plan.playlists) {
    const previous = playlist.diff ? playlist.diff.previous_positions : null;
    const head = el("thead", {}, el("tr", {}, ...["#", "Música", "Artista", "BPM", "Gênero", "Antes"].map((h) => el("th", {}, h))));
    const body = el("tbody", {}, ...playlist.tracks.map((item, i) => trackRow(item, i, previous ? previous[i] : undefined)));
    const card = el("article", { class: "card" }, el("h3", {}, playlist.name), el("p", { class: "meta" }, playlist.description));
    if (playlist.missing_slots.length) card.append(el("p", { class: "warn" }, `Sem música encontrada: ${playlist.missing_slots.join(", ")}`));
    card.append(el("div", { class: "table-wrap" }, el("table", {}, head, body)));
    preview.append(card);
  }
  const actions = el("div", { class: "actions" },
    el("button", { type: "button", onclick: () => run("Criando no Spotify...", () => api("/api/apply", { mode: "new" })) },
      plan.playlists.length > 1 ? `Criar ${plan.playlists.length} playlists novas` : "Criar playlist nova"));
  if (plan.can_replace_in_place) {
    const replace = () => {
      if (confirm("Substituir a ordem da playlist original? Dá para desfazer depois.")) {
        run("Reordenando a original...", () => api("/api/apply", { mode: "replace" }));
      }
    };
    actions.append(el("button", { type: "button", class: "ghost", onclick: replace }, "Substituir a original"));
  }
  preview.append(actions);
  preview.hidden = false;
}

function renderResult(result) {
  const links = el("ul", { class: "links" },
    ...result.urls.map((url) => el("li", {}, el("a", { href: url, target: "_blank", rel: "noopener" }, "Abrir no Spotify"))));
  const box = el("div", { class: "actions" }, links);
  if (result.undo_id !== null && result.undo_id !== undefined) {
    box.append(el("button", { type: "button", class: "ghost",
      onclick: () => run("Desfazendo...", () => api("/api/undo", { undo_id: result.undo_id })) }, "Desfazer"));
  }
  preview.replaceChildren(el("h2", {}, "Feito"), box);
  preview.hidden = false;
}

function greet() {
  say("agent", "Oi! Posso reorganizar uma playlist sua (por BPM ou por gênero) ou montar uma nova com tema, " +
    "tipo um prédio com Primeiro Andar, Segundo Andar... O que vamos fazer?");
}

form.addEventListener("submit", (event) => {
  event.preventDefault();
  const text = input.value.trim();
  if (!text) return;
  input.value = "";
  say("user", text);
  run("Pensando... (o agente leva uns 10 segundos)", () => api("/api/chat", { text }));
});

document.getElementById("reset").addEventListener("click", async () => {
  await api("/api/reset", {});
  log.replaceChildren();
  preview.replaceChildren();
  preview.hidden = true;
  greet();
});

async function boot() {
  try {
    const status = await api("/api/status");
    statusEl.textContent = status.logged_in ? "Spotify conectado" : "Spotify desconectado";
    statusEl.classList.toggle("ok", status.logged_in);
    loginLink.hidden = status.logged_in;
    if (!status.claude_ok) {
      say("error", "Claude Code não encontrado. Rode `claude` no terminal, faça login e reinicie o app.");
    }
  } catch (error) {
    say("error", error.message);
  }
  greet();
}

boot();
