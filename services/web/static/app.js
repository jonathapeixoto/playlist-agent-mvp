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
  if (!response.ok) {
    if (data.report) renderReport(data.report);
    throw new Error(typeof data.detail === "string" ? data.detail : `Erro ${response.status}`);
  }
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
  for (const stale of log.querySelectorAll(".options")) stale.remove();
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
  say("agent", "Oi! Me diga o que você quer fazer com suas playlists. Posso reordenar por andamento, " +
    "agrupar por gênero, dividir uma playlist grande em várias, ou montar uma nova a partir de um tema.");
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
      const engine = await api("/api/llm").catch(() => ({ description: "" }));
      if (engine.description.startsWith("Claude Code")) {
        say("error", "Claude Code não encontrado. Rode `claude` no terminal e faça login, ou escolha outro motor em Motor de IA.");
      }
    }
  } catch (error) {
    say("error", error.message);
  }
  greet();
}

const panel = document.getElementById("llm-panel");
const presetSelect = document.getElementById("llm-preset");
const baseUrlInput = document.getElementById("llm-base-url");
const modelInput = document.getElementById("llm-model");
const keyInput = document.getElementById("llm-key");
const helpText = document.getElementById("llm-help");
const reportList = document.getElementById("llm-report");
const currentText = document.getElementById("llm-current");
let presets = [];

function presetByKey(key) {
  return presets.find((p) => p.key === key) || null;
}

function applyPreset(key, { keepFields = false } = {}) {
  const preset = presetByKey(key);
  if (!preset) return;
  if (!keepFields) {
    baseUrlInput.value = preset.base_url;
    modelInput.value = preset.model;
    keyInput.value = "";
  }
  document.getElementById("llm-base-url-row").hidden = key !== "custom";
  document.getElementById("llm-key-row").hidden = !preset.needs_key;
  helpText.replaceChildren();
  if (preset.help_url) {
    helpText.append(
      preset.needs_key ? "Pegue a chave em " : "Saiba mais em ",
      el("a", { href: preset.help_url, target: "_blank", rel: "noopener" }, preset.help_url));
  }
}

function renderReport(report) {
  reportList.replaceChildren(
    ...report.checks.map((c) =>
      el("li", { class: c.ok ? "" : "warn" }, `${c.ok ? "OK" : "FALHOU"} · ${c.name}: ${c.detail} (${c.latency_s}s)`)));
}

async function loadEngine() {
  const data = await api("/api/llm");
  presets = data.presets;
  presetSelect.replaceChildren(...presets.map((p) => el("option", { value: p.key }, p.label)));
  presetSelect.value = data.current.preset;
  applyPreset(data.current.preset);
  baseUrlInput.value = data.current.base_url;
  modelInput.value = data.current.model;
  currentText.textContent = data.current.has_key
    ? `Em uso: ${data.description} (chave salva)`
    : `Em uso: ${data.description}`;
}

function engineBody() {
  return {
    preset: presetSelect.value,
    model: modelInput.value.trim(),
    base_url: baseUrlInput.value.trim(),
    api_key: keyInput.value,
  };
}

async function submitEngine(path) {
  reportList.replaceChildren(el("li", {}, "Testando o motor: 3 chamadas reais, pode levar alguns segundos..."));
  setBusy(true);
  try {
    const data = await api(path, engineBody());
    renderReport(data.report || data);
    if (data.ok && path === "/api/llm") {
      currentText.textContent = `Em uso: ${data.description}`;
      keyInput.value = "";
      say("agent", `Pronto: agora estou usando ${data.description}.`);
    }
  } catch (error) {
    reportList.replaceChildren(el("li", { class: "warn" }, error.message));
  } finally {
    setBusy(false);
  }
}

presetSelect.addEventListener("change", () => applyPreset(presetSelect.value));
document.getElementById("engine").addEventListener("click", async () => {
  panel.hidden = !panel.hidden;
  if (!panel.hidden) {
    reportList.replaceChildren();
    try {
      await loadEngine();
    } catch (error) {
      reportList.replaceChildren(el("li", { class: "warn" }, error.message));
    }
  }
});
document.getElementById("llm-close").addEventListener("click", () => {
  panel.hidden = true;
});
document.getElementById("llm-only-test").addEventListener("click", () => submitEngine("/api/llm/test"));
document.getElementById("llm-form").addEventListener("submit", (event) => {
  event.preventDefault();
  submitEngine("/api/llm");
});

boot();
