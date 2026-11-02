"use strict";

/* Radar IA — application de lecture (PWA, sans dépendance ni étape de build).
   Les données sont produites chaque jour par le pipeline dans ./data/. */

const DATA = "data/";
const TOP_COUNT = 5;
const state = { index: null, days: {}, tag: null, query: "" };
const view = document.getElementById("view");
const subtitle = document.getElementById("subtitle");

/* ---------- Stockage local (favoris, lus) ---------- */

const store = {
  get(key, fallback) {
    try { return JSON.parse(localStorage.getItem(key)) ?? fallback; } catch { return fallback; }
  },
  set(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch { /* stockage indisponible */ }
  },
};
const favorites = () => store.get("radar.favorites", {});
const readMap = () => store.get("radar.read", {});

function toggleFavorite(item, date) {
  const favs = favorites();
  if (favs[item.id]) delete favs[item.id];
  else favs[item.id] = { ...item, _date: date, _saved: new Date().toISOString() };
  store.set("radar.favorites", favs);
  return Boolean(favs[item.id]);
}

function markRead(id) {
  const read = readMap();
  read[id] = Date.now();
  const entries = Object.entries(read).sort((a, b) => b[1] - a[1]).slice(0, 800);
  store.set("radar.read", Object.fromEntries(entries));
}

/* ---------- Utilitaires ---------- */

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

function safeUrl(url) {
  try {
    const u = new URL(url);
    return u.protocol === "https:" || u.protocol === "http:" ? u.href : null;
  } catch { return null; }
}

const rtf = new Intl.RelativeTimeFormat("fr", { numeric: "auto" });
function timeAgo(iso) {
  const diff = (new Date(iso) - Date.now()) / 1000;
  const steps = [[60, "second"], [3600, "minute"], [86400, "hour"], [604800, "day"], [Infinity, "week"]];
  const units = { second: 1, minute: 60, hour: 3600, day: 86400, week: 604800 };
  for (const [limit, unit] of steps) {
    if (Math.abs(diff) < limit) return rtf.format(Math.round(diff / units[unit]), unit);
  }
  return "";
}

function formatDay(date) {
  return new Date(date + "T12:00:00").toLocaleDateString("fr-FR",
    { weekday: "long", day: "numeric", month: "long", year: "numeric" });
}

const tagLabel = (id) => state.index?.tags?.[id] || id;

async function fetchJson(path) {
  const resp = await fetch(DATA + path, { cache: "no-cache" });
  if (!resp.ok) throw new Error(`${path} : ${resp.status}`);
  return resp.json();
}

async function loadIndex(force = false) {
  if (!state.index || force) state.index = await fetchJson("index.json");
  return state.index;
}

async function loadDay(date, force = false) {
  if (!state.days[date] || force) state.days[date] = await fetchJson(`daily/${date}.json`);
  return state.days[date];
}

/* ---------- Composants ---------- */

function cardHtml(item, date, { top = false } = {}) {
  const read = readMap()[item.id] ? " read" : "";
  const fav = favorites()[item.id] ? '<span class="fav-mark" title="Favori">★</span>' : "";
  const text = item.summary_kind === "ai" ? item.summary : item.excerpt;
  const tags = (item.tags || []).map((t) => `<span class="tag">${esc(tagLabel(t))}</span>`).join("");
  const Heading = top ? "h2" : "h3";
  return `
    <a class="card${top ? " top" : ""}${read}" href="#/article/${esc(date)}/${esc(item.id)}">
      <div class="meta">
        <span class="score" title="Score d'importance">${esc(item.score)}</span>
        <span>${esc(item.source_name)}</span>·<span>${esc(timeAgo(item.published))}</span>
        ${item.also_in?.length ? `<span>· +${item.also_in.length} source(s)</span>` : ""} ${fav}
      </div>
      <${Heading}>${esc(item.title)}</${Heading}>
      ${text ? `<p class="snippet">${esc(text)}</p>` : ""}
      ${tags ? `<div class="tags">${tags}</div>` : ""}
    </a>`;
}

function filterItems(items) {
  const q = state.query.trim().toLowerCase();
  return items.filter((i) =>
    (!state.tag || (i.tags || []).includes(state.tag)) &&
    (!q || `${i.title} ${i.summary} ${i.excerpt} ${i.source_name}`.toLowerCase().includes(q)));
}

function toolbarHtml(items) {
  const counts = {};
  items.forEach((i) => (i.tags || []).forEach((t) => { counts[t] = (counts[t] || 0) + 1; }));
  const chips = Object.entries(counts).sort((a, b) => b[1] - a[1])
    .map(([t, n]) => `<button class="chip" data-tag="${esc(t)}" aria-pressed="${state.tag === t}">${esc(tagLabel(t))} · ${n}</button>`)
    .join("");
  return `
    <div class="toolbar">
      <input class="search" type="search" placeholder="Filtrer (mot-clé, source…)" value="${esc(state.query)}" aria-label="Filtrer">
      <div class="chips"><button class="chip" data-tag="" aria-pressed="${!state.tag}">Tous</button>${chips}</div>
    </div>
    <div id="list"></div>`;
}

function bindToolbar(renderList) {
  view.querySelector(".search").addEventListener("input", (e) => { state.query = e.target.value; renderList(); });
  view.querySelectorAll(".chip").forEach((chip) => chip.addEventListener("click", () => {
    state.tag = chip.dataset.tag || null;
    view.querySelectorAll(".chip").forEach((c) => c.setAttribute("aria-pressed", String((c.dataset.tag || null) === state.tag)));
    renderList();
  }));
  renderList();
}

function emptyState(message) {
  view.innerHTML = `<p class="empty">${message}</p>`;
}

/* ---------- Vues ---------- */

async function renderDay(date, mode, archived = false) {
  const index = await loadIndex();
  date = date || index.days?.[0]?.date;
  if (!date) {
    subtitle.textContent = "";
    return emptyState("Pas encore de données.<br>Le pipeline n'a pas encore tourné : lance le workflow « Radar quotidien » sur GitHub.");
  }
  const day = await loadDay(date);
  subtitle.textContent = formatDay(date);
  const items = day.items.filter((i) => (mode === "research" ? i.category === "research" : i.category !== "research"));
  if (!items.length) return emptyState(mode === "research" ? "Aucun article de recherche ce jour-là." : "Aucune actualité ce jour-là.");

  const switcher = archived
    ? `<p class="note"><a href="#/archives">← Archives</a> · ${mode === "research"
        ? `<a href="#/jour/${esc(date)}">Actualités</a> · <strong>Recherche</strong>`
        : `<strong>Actualités</strong> · <a href="#/jour/${esc(date)}/recherche">Recherche</a>`}</p>`
    : "";
  view.innerHTML = switcher + toolbarHtml(items);
  const list = view.querySelector("#list");
  bindToolbar(() => {
    const shown = filterItems(items);
    if (!shown.length) { list.innerHTML = '<p class="empty">Aucun résultat pour ce filtre.</p>'; return; }
    const filtering = state.tag || state.query;
    if (mode === "research" || filtering) {
      list.innerHTML = shown.map((i) => cardHtml(i, date)).join("");
      return;
    }
    list.innerHTML =
      `<p class="section-title">À la une</p>${shown.slice(0, TOP_COUNT).map((i) => cardHtml(i, date, { top: true })).join("")}` +
      (shown.length > TOP_COUNT ? `<p class="section-title">Le reste du jour</p>${shown.slice(TOP_COUNT).map((i) => cardHtml(i, date)).join("")}` : "");
  });
}

async function renderArticle(date, id) {
  let item = favorites()[id];
  try { item = (await loadDay(date)).items.find((i) => i.id === id) || item; } catch { /* hors ligne : favori */ }
  if (!item) return emptyState("Article introuvable.");
  markRead(id);
  subtitle.textContent = formatDay(date);

  const url = safeUrl(item.url);
  const pdf = safeUrl(item.pdf_url);
  const discussion = safeUrl(item.discussion_url);
  const isAi = item.summary_kind === "ai" && item.summary;
  const tags = (item.tags || []).map((t) => `<span class="tag">${esc(tagLabel(t))}</span>`).join("");
  const authors = (item.authors || []).filter(Boolean);

  view.innerHTML = `
    <article class="article">
      <a class="back" href="#" onclick="history.back(); return false;">← Retour</a>
      <div class="meta"><span class="score">${esc(item.score)}</span>
        <span>${esc(item.source_name)}</span>·<span>${esc(new Date(item.published).toLocaleString("fr-FR", { dateStyle: "medium", timeStyle: "short" }))}</span></div>
      <h2>${esc(item.title)}</h2>
      ${tags ? `<div class="tags">${tags}</div>` : ""}
      ${authors.length ? `<p class="note">${esc(authors.join(", "))}</p>` : ""}
      <p class="label">${isAi ? "Résumé IA" : "Extrait de la source"}</p>
      <p class="body">${esc(isAi ? item.summary : item.excerpt || "Pas d'extrait fourni par la source.")}</p>
      ${isAi && item.excerpt ? `<p class="label">Extrait original</p><p class="note">${esc(item.excerpt)}</p>` : ""}
      ${item.also_in?.length ? `<p class="note">Aussi repris par : ${esc(item.also_in.join(", "))}</p>` : ""}
      <div class="actions">
        ${url ? `<a class="btn primary" href="${esc(url)}" target="_blank" rel="noopener noreferrer">Lire l'original ↗</a>` : ""}
        ${pdf ? `<a class="btn" href="${esc(pdf)}" target="_blank" rel="noopener noreferrer">PDF ↗</a>` : ""}
        ${discussion ? `<a class="btn" href="${esc(discussion)}" target="_blank" rel="noopener noreferrer">Discussion ↗</a>` : ""}
        <button class="btn" id="fav" type="button"></button>
        ${navigator.share && url ? '<button class="btn" id="share" type="button">Partager</button>' : ""}
      </div>
      ${isAi ? '<p class="note">Résumé généré automatiquement : vérifie les détails dans la source.</p>' : ""}
    </article>`;

  const favBtn = view.querySelector("#fav");
  const paint = (on) => { favBtn.textContent = on ? "★ Dans les favoris" : "☆ Ajouter aux favoris"; };
  paint(Boolean(favorites()[id]));
  favBtn.addEventListener("click", () => paint(toggleFavorite(item, date)));
  view.querySelector("#share")?.addEventListener("click", () =>
    navigator.share({ title: item.title, url }).catch(() => {}));
}

function renderFavorites() {
  subtitle.textContent = "Favoris";
  const favs = Object.values(favorites()).sort((a, b) => (b._saved || "").localeCompare(a._saved || ""));
  if (!favs.length) return emptyState("Aucun favori pour l'instant.<br>Ouvre un article puis « Ajouter aux favoris ».");
  view.innerHTML = favs.map((i) => cardHtml(i, i._date)).join("") +
    '<p class="note">Les favoris sont gardés sur cet appareil uniquement.</p>';
}

async function renderArchives() {
  const index = await loadIndex();
  subtitle.textContent = "Archives";
  if (!index.days?.length) return emptyState("Pas encore de données.");
  const days = index.days.map((d) =>
    `<li><a href="#/jour/${esc(d.date)}"><span>${esc(formatDay(d.date))}</span><span class="note">${esc(d.count)}</span></a></li>`).join("");
  const sources = Object.entries(index.sources || {})
    .map(([id, s]) => `<tr><td>${esc(id)}</td><td>${esc(s)}</td></tr>`).join("");
  view.innerHTML = `
    <ul class="day-list">${days}</ul>
    <p class="section-title">Dernière collecte</p>
    <p class="note">${esc(new Date(index.generated_at).toLocaleString("fr-FR"))} · résumés : ${esc(index.llm === "none" ? "extraits (pas de LLM configuré)" : index.llm)}</p>
    <table class="status">${sources}</table>`;
}

/* ---------- Routeur ---------- */

async function route() {
  const parts = location.hash.replace(/^#\/?/, "").split("/").filter(Boolean).map(decodeURIComponent);
  const [page, a, b] = parts;
  const tab = { recherche: "research", favoris: "favorites", archives: "archives" }[page] || "today";
  document.querySelectorAll(".tabbar a").forEach((link) => {
    if (link.dataset.tab === tab && page !== "article") link.setAttribute("aria-current", "page");
    else link.removeAttribute("aria-current");
  });
  if (page !== "article") { state.tag = null; state.query = ""; }

  try {
    if (page === "article") await renderArticle(a, b);
    else if (page === "recherche") await renderDay(null, "research");
    else if (page === "favoris") renderFavorites();
    else if (page === "archives") await renderArchives();
    else if (page === "jour") await renderDay(a, b === "recherche" ? "research" : "news", true);
    else await renderDay(null, "news");
  } catch (err) {
    console.error(err);
    emptyState("Impossible de charger les données.<br>Vérifie ta connexion puis réessaie.");
  }
  if (page !== "article") window.scrollTo(0, 0);
}

document.getElementById("refresh").addEventListener("click", async () => {
  state.index = null; state.days = {};
  await route();
});
window.addEventListener("hashchange", route);
route();

if ("serviceWorker" in navigator) {
  window.addEventListener("load", () => navigator.serviceWorker.register("sw.js").catch(() => {}));
}
