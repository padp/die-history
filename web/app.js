let scope = "paducah";
let query = "";
let activeDie = null;

const listEl = document.getElementById("die-list");
const detailEl = document.getElementById("die-detail");
const totalsEl = document.getElementById("totals");

function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, c => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  }[c]));
}

async function loadSummary() {
  const r = await fetch("/api/summary");
  const s = await r.json();
  totalsEl.textContent =
    `${s.n_dies} dies (${s.n_paducah} Paducah) · ${s.n_copies} copies · ` +
    `${s.n_entries.toLocaleString()} entries` +
    (s.n_errors ? ` · ${s.n_errors} parse errors` : "");
}

async function loadList() {
  listEl.innerHTML = '<p class="dim pad">loading…</p>';
  const params = new URLSearchParams({
    paducah_only: scope === "paducah" ? "1" : "0",
    q: query,
  });
  const r = await fetch(`/api/dies?${params}`);
  const rows = await r.json();

  if (!rows.length) {
    listEl.innerHTML = '<p class="dim pad">No dies match.</p>';
    return;
  }

  listEl.innerHTML = rows.map(d => `
    <div class="die-row ${d.die_no === activeDie ? "active" : ""}" data-die="${esc(d.die_no)}">
      <div class="top">
        <span class="die-no">${esc(d.die_no)}</span>
        <span class="desc">${esc(d.description || "")}</span>
        ${d.is_paducah ? '<span class="badge paducah">Paducah</span>' : ""}
        ${d.parse_error ? '<span class="badge error">parse error</span>' : ""}
      </div>
      <div class="meta">
        <span>${d.n_copies} ${d.n_copies === 1 ? "copy" : "copies"}</span>
        <span>${d.n_entries.toLocaleString()} entries</span>
        <span>${d.total_billets ? d.total_billets.toLocaleString() + " billets" : ""}</span>
        <span>${fmtLbs(d.total_lbs)}${d.n_copies_with_lbs < d.n_copies ? ` (${d.n_copies_with_lbs}/${d.n_copies} copies)` : ""}</span>
        <span>${d.first_date ? `${d.first_date} → ${d.last_date}` : ""}</span>
      </div>
    </div>
  `).join("");

  listEl.querySelectorAll(".die-row").forEach(el => {
    el.addEventListener("click", () => selectDie(el.dataset.die));
  });
}

function fmtDate(iso) {
  return iso || "—";
}

function fmtLbs(n) {
  if (n === null || n === undefined) return "";
  return `${Math.round(n).toLocaleString()} lb`;
}

async function selectDie(dieNo) {
  activeDie = dieNo;
  listEl.querySelectorAll(".die-row").forEach(el => {
    el.classList.toggle("active", el.dataset.die === dieNo);
  });

  detailEl.innerHTML = '<p class="dim pad">loading…</p>';
  const r = await fetch(`/api/die/${encodeURIComponent(dieNo)}`);
  if (!r.ok) {
    detailEl.innerHTML = '<p class="dim pad">Not found.</p>';
    return;
  }
  const die = await r.json();

  if (die.parse_error) {
    detailEl.innerHTML = `
      <h2>${esc(die.die_no)} <span class="dim">${esc(die.description || "")}</span></h2>
      <p class="sub">${esc(die.history_file || "")}</p>
      <p class="badge error">parse error</p>
      <p class="dim">${esc(die.parse_error)}</p>
    `;
    return;
  }

  const copiesHtml = die.copies.map(c => `
    <div class="copy-card">
      <div class="copy-head">
        <b>${esc(die.die_no)}-${esc(c.copy_no)}</b>
        <span class="stat">backer ${esc(c.backer_number ?? "—")}</span>
        <span class="stat">bolster ${esc(c.bolster_number ?? "—")}</span>
        <span class="stat">nitrided ${c.times_nitrided ?? "—"}×</span>
        <span class="stat">${c.total_billets_lifetime ? c.total_billets_lifetime.toLocaleString() + " billets" : ""}</span>
        <span class="stat">${fmtDate(c.first_date)} → ${fmtDate(c.last_date)}</span>
        ${c.gross_lbs != null ? `
          <span class="stat lbs" title="${c.billets_total} billets × (${c.billet_length_median_in.toFixed(2)}in median billet − ${c.butt_length_in}in butt) × 4.9 lb/in, from ${c.billet_length_n} matched billets">
            ${fmtLbs(c.gross_lbs)} extruded
          </span>` : `
          <span class="stat dim">no billet-length match</span>`}
      </div>
      <table class="entries">
        <thead><tr><th>Date</th><th>Billets</th><th>Pull code</th><th>Type</th></tr></thead>
        <tbody>
          ${c.entries.map(e => `
            <tr>
              <td>${fmtDate(e.entry_date)}</td>
              <td>${esc(e.billets_raw ?? "")}</td>
              <td>${esc(e.pull_code_raw ?? "")}</td>
              <td><span class="type-tag ${e.entry_type}">${e.entry_type}</span></td>
            </tr>
          `).join("") || '<tr><td colspan="4" class="dim">no entries</td></tr>'}
        </tbody>
      </table>
    </div>
  `).join("");

  detailEl.innerHTML = `
    <h2>${esc(die.die_no)} <span class="dim">${esc(die.description || "")}</span></h2>
    <p class="sub">${esc(die.history_file || "")} · ${die.copies.length} ${die.copies.length === 1 ? "copy" : "copies"}</p>
    ${copiesHtml || '<p class="dim">No copies parsed.</p>'}
  `;
}

document.querySelectorAll(".scopebtn").forEach(btn => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".scopebtn").forEach(b => b.classList.remove("on"));
    btn.classList.add("on");
    scope = btn.dataset.scope;
    loadList();
  });
});

let searchTimer;
document.getElementById("search").addEventListener("input", e => {
  clearTimeout(searchTimer);
  searchTimer = setTimeout(() => {
    query = e.target.value;
    loadList();
  }, 200);
});

loadSummary();
loadList();
