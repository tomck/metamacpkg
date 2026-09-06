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

function parseProposal(body) {
  const m = String(body || "").match(/<!--\s*metamacpkg-proposal\s*(\{.*?\})\s*-->/s);
  if (!m) return null;
  try {
    const p = JSON.parse(m[1]);
    if (!p.pair || !p.source || !p.decision) return null;
    return p;
  } catch { return null; }
}

function findExisting(card, proposals) {
  return proposals.filter(p => p.pair === card.pair && p.source === card.source);
}

// Identical verdicts already on file: point at the issue instead of
// opening a duplicate. Returns banner html plus the set of targets
// (and no-equivalent flag) that should be locked on this card.
function existingState(card, existing) {
  const locked = new Set(), noeq = { locked: false };
  const items = existing.map(p => {
    if ((p.decision === "confirm" || p.decision === "propose") && p.target)
      locked.add(p.target);
    if (p.decision === "no-equivalent") noeq.locked = true;
    const what = p.decision === "no-equivalent" ? "no equivalent" : `→ ${p.target || "?"}`;
    return `<li><a href="https://github.com/${REPO}/issues/${p.number}">#${p.number}</a> ` +
      `${esc(what)} by @${esc(p.user)}</li>`;
  }).join("");
  if (!existing.length) return { html: "", locked, noeqLocked: false };
  return { html: `<div class="card existing"><strong>Already proposed:</strong><ul>${items}</ul>
    <p class="meta">Add a 👍 reaction on the issue to approve it instead of opening a duplicate.</p></div>`,
    locked, noeqLocked: noeq.locked };
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
  const st = existingState(c, findExisting(c, openProposals));
  const cands = c.lookalikes.map((l, i) => {
    const dup = st.locked.has(l.target);
    return `
    <div class="cand">
      <div class="row"><strong>${esc(l.target)}</strong>
        ${dup ? `<span class="meta">proposed — vote on the issue above</span>`
              : `<button class="confirm" data-i="${i}">Confirm [${i + 1}]</button>`}</div>
      <div class="meta">${homepage(l.homepage)}${l.version ? " · v" + esc(l.version) : ""}</div>
      <p class="desc">${esc(l.desc) || "<span class='meta'>no description</span>"}</p>
    </div>`; }).join("");
  main.innerHTML = `
    <div class="card">
      <h2>${esc(c.source)}</h2>
      <div><span class="chip">${esc(c.from.manager)} ${esc(c.from.type)}</span>
        <span class="chip">→ ${esc(c.to.manager)}</span>
        ${c.version ? `<span class="chip">v${esc(c.version)}</span>` : ""}</div>
      <p class="desc">${esc(c.desc) || "<span class='meta'>no description</span>"}</p>
      <div class="meta">${homepage(c.homepage)}</div>
      <details><summary>Why is this uncertain?</summary><p>${esc(c.evidence)}</p></details>
      ${st.html}
      ${cands || "<p class='meta'>No lookalikes found — check search before confirming anything.</p>"}
      <div class="actions">
        ${st.noeqLocked
          ? `<span class="meta">No-equivalent already proposed — vote on the issue above.</span>`
          : `<button class="danger" id="noeq">No equivalent [0]</button>`}
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
  const noeqBtn = document.getElementById("noeq");
  if (noeqBtn) noeqBtn.addEventListener("click", () => submit(c, "no-equivalent", ""));
  window.__current = { card: c, locked: st.locked, noeqLocked: st.noeqLocked };
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

let openProposals = [];

async function fetchOpenProposals() {
  openProposals = [];
  try {
    let url = `https://api.github.com/search/issues` +
      `?q=repo:${REPO}+label:${LABEL}+state:open&per_page=100`;
    for (let page = 0; page < 3 && url; page++) {
      const r = await fetch(url, { headers: { Accept: "application/vnd.github+json" } });
      const data = await r.json();
      for (const issue of data.items || []) {
        const p = parseProposal(issue.body);
        if (p) openProposals.push({ ...p, number: issue.number,
                                    user: (issue.user || {}).login || "?" });
      }
      const link = r.headers.get("Link") || "";
      const m = link.match(/<([^>]+)>;\s*rel="next"/);
      url = m ? m[1] : null;
    }
    const n = openProposals.length;
    document.getElementById("submitted").textContent =
      `${n} proposal${n === 1 ? "" : "s"} awaiting review — votes decide.`;
  } catch { /* offline-friendly: skip */ }
  render();
}

document.addEventListener("keydown", e => {
  if (e.target.matches("input, select, textarea")) return;
  if (idx >= queue.length) return;
  const cur = window.__current;
  if (!cur) return;
  const c = cur.card;
  if (e.key >= "1" && e.key <= "8") {
    const i = +e.key - 1;
    const t = c.lookalikes[i] && c.lookalikes[i].target;
    if (t && !cur.locked.has(t)) submit(c, "confirm", t);
  } else if (e.key === "0") {
    if (!cur.noeqLocked) submit(c, "no-equivalent", "");
  } else if (e.key === "ArrowRight") {
    idx++; render();
  }
});
pairSel.addEventListener("change", load);
load();
fetchOpenProposals();
if (typeof window !== "undefined")
  window.__review = { issueUrl, parseProposal, findExisting, existingState };
