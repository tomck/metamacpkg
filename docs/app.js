/* Review queue: renders cards from docs/data/queue-*.json, submits
   verdicts as pre-filled GitHub issues (no backend). */
"use strict";
const REPO = "tomck/metamacpkg"; // fork? change this to your repo
const LABEL = "mapping-review";

const main = document.getElementById("main");
const pairSel = document.getElementById("pair");
const progressEl = document.getElementById("progress");
let queue = [], idx = 0, done = 0;
let proposed = null; // target selected via search

function seenKey(card) { return card.pair + ":" + card.source; }
function isSeen(card) {
  try { return localStorage.getItem("seen:" + seenKey(card)) === "1"; }
  catch { return false; }
}
function markSeen(card) {
  try { localStorage.setItem("seen:" + seenKey(card), "1"); } catch {}
  done++;
}

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c =>
    ({"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"}[c]));
}

function issueUrl(card, decision, target) {
  const title = `[mapping] ${card.pair}: ${card.source} -> ${target || "∅"}`;
  const proposal = { pair: card.pair, source: card.source,
                     decision, target: target || "", comment: "" };
  const body =
`Review-site verdict (needs maintainer check before entering the database).

- pair: ${card.pair}
- source: ${card.source} (${card.from.manager}/${card.from.type})
- decision: ${decision}${target ? "\n- target: " + target : ""}
- evidence shown: ${card.evidence}

<!-- metamacpkg-proposal ${JSON.stringify(proposal)} -->`;
  const q = new URLSearchParams({ title, body, labels: LABEL });
  return `https://github.com/${REPO}/issues/new?${q.toString()}`;
}

function homepage(link, text) {
  if (!link) return "";
  return `<a href="${esc(link)}" rel="noopener">${esc(text || link)}</a>`;
}

function render() {
  while (idx < queue.length && isSeen(queue[idx])) idx++;
  progressEl.textContent =
    queue.length ? `Card ${Math.min(idx + 1, queue.length)} of ${queue.length} · reviewed here: ${done}` : "";
  if (idx >= queue.length) {
    main.innerHTML = `<div class="card"><h2>Queue clear</h2>
      <p class="desc">Every card in this direction has been reviewed on this browser.
      Pick another direction above, or browse submitted proposals.</p></div>`;
    return;
  }
  proposed = null;
  const c = queue[idx];
  const cands = c.lookalikes.map((l, i) => `
    <div class="cand">
      <div class="row"><strong>${esc(l.target)}</strong>
        <button class="confirm" data-i="${i}">Confirm [${i + 1}]</button></div>
      <div class="meta">${homepage(l.homepage)}${l.version ? " · v" + esc(l.version) : ""}</div>
      <p class="desc">${esc(l.desc) || "<span class='meta'>no description</span>"}</p>
    </div>`).join("");
  main.innerHTML = `
    <div class="card">
      <h2>${esc(c.source)}</h2>
      <div><span class="chip">${esc(c.from.manager)} ${esc(c.from.type)}</span>
        <span class="chip">→ ${esc(c.to.manager)}</span>
        ${c.version ? `<span class="chip">v${esc(c.version)}</span>` : ""}</div>
      <p class="desc">${esc(c.desc) || "<span class='meta'>no description</span>"}</p>
      <div class="meta">${homepage(c.homepage)}</div>
      <details><summary>Why is this uncertain?</summary><p>${esc(c.evidence)}</p></details>
      ${cands || "<p class='meta'>No lookalikes found — check search before confirming anything.</p>"}
      <div class="actions">
        <button class="danger" id="noeq">No equivalent [0]</button>
        <button id="skip">Skip [→]</button>
        <button id="other">Propose different…</button>
      </div>
      <div class="searchbox" id="searchbox" hidden>
        <label>Search all packages
          <input type="text" id="q" autocomplete="off"
                 placeholder="type at least 2 characters"></label>
        <ul id="results"></ul>
        <div><button class="confirm" id="propose" disabled>Propose selected</button></div>
      </div>
    </div>`;
  main.querySelectorAll("button.confirm[data-i]").forEach(b =>
    b.addEventListener("click", () => submit(c, "confirm", c.lookalikes[+b.dataset.i].target)));
  document.getElementById("noeq").addEventListener("click", () => submit(c, "no-equivalent", ""));
  document.getElementById("skip").addEventListener("click", () => { idx++; render(); });
  document.getElementById("other").addEventListener("click", () => {
    const box = document.getElementById("searchbox");
    box.hidden = !box.hidden;
    if (!box.hidden) document.getElementById("q").focus();
  });
  document.getElementById("q").addEventListener("input", e => search(e.target.value));
  document.getElementById("propose").addEventListener("click", () => {
    if (proposed) submit(c, "propose", proposed);
  });
}

function submit(card, decision, target) {
  markSeen(card);
  window.open(issueUrl(card, decision, target), "_blank", "noopener");
  idx++;
  render();
}

const shardCache = {};
async function search(text) {
  const box = document.getElementById("results");
  const prop = document.getElementById("propose");
  proposed = null; prop.disabled = true; prop.textContent = "Propose selected";
  const q = text.trim().toLowerCase();
  if (q.length < 2) { box.innerHTML = ""; return; }
  let ch = q.replace(/[^a-z0-9]/g, "").charAt(0) || "other";
  if (/\d/.test(ch)) ch = "0-9";
  try {
    shardCache[ch] ??= await (await fetch(`data/names/${ch}.json`)).json();
  } catch { box.innerHTML = ""; return; }
  const hits = shardCache[ch].filter(e => e.n.toLowerCase().includes(q)).slice(0, 8);
  box.innerHTML = hits.map((h, i) =>
    `<li><button data-i="${i}" aria-pressed="false">${esc(h.n)}
     <span class="meta">(${esc(h.m)}/${esc(h.t)})</span></button></li>`).join("")
    || `<li class="meta">No matches.</li>`;
  box.querySelectorAll("button").forEach(b => b.addEventListener("click", () => {
    box.querySelectorAll("button").forEach(x => x.setAttribute("aria-pressed", "false"));
    b.setAttribute("aria-pressed", "true");
    proposed = hits[+b.dataset.i].n;
    prop.disabled = false;
    prop.textContent = `Propose ${proposed}`;
  }));
}

async function load() {
  document.getElementById("status") && (main.innerHTML = "<p>Loading queue…</p>");
  idx = 0; done = 0;
  try {
    const r = await fetch(`data/queue-${pairSel.value}.json`);
    queue = (await r.json()).cards;
  } catch { queue = []; }
  render();
}

async function submittedCount() {
  try {
    const r = await fetch(
      `https://api.github.com/search/issues?q=repo:${REPO}+label:${LABEL}+state:open&per_page=1`);
    const n = (await r.json()).total_count;
    document.getElementById("submitted").textContent =
      `${n} proposal${n === 1 ? "" : "s"} awaiting maintainer review.`;
  } catch { /* offline-friendly: skip */ }
}

document.addEventListener("keydown", e => {
  if (e.target.matches("input, select, textarea")) return;
  if (idx >= queue.length) return;
  const c = queue[idx];
  if (e.key >= "1" && e.key <= "8") {
    const i = +e.key - 1;
    if (c.lookalikes[i]) submit(c, "confirm", c.lookalikes[i].target);
  } else if (e.key === "0") {
    submit(c, "no-equivalent", "");
  } else if (e.key === "ArrowRight") {
    idx++; render();
  }
});
pairSel.addEventListener("change", load);
load();
submittedCount();
if (typeof window !== "undefined") window.__review = { issueUrl };
