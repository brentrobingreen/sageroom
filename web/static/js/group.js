import { requireAuth, setupSessionMonitor } from "./auth.js";
import { getBrains, startGroupChat, getGroupSessionStatus, getGroupSession, getGroupSessions } from "./api.js";

let brains = [];
let selectedSlugs = new Set();
let pollInterval = null;

const brainGrid     = document.getElementById("brain-grid");
const questionInput = document.getElementById("question");
const submitBtn     = document.getElementById("submit-btn");
const selectedCount = document.getElementById("selected-count");
const resultsArea   = document.getElementById("results-area");
const sessionsList  = document.getElementById("sessions-list");
const loadingArea   = document.getElementById("loading-area");

async function init() {
  await requireAuth();
  await setupSessionMonitor();
  await Promise.all([loadBrains(), loadPastSessions()]);
}

async function loadBrains() {
  try {
    brains = await getBrains();
    renderBrainGrid();
  } catch (e) {
    showError(e.message);
  }
}

function renderBrainGrid() {
  brainGrid.innerHTML = "";
  for (const brain of brains) {
    const card = document.createElement("div");
    card.className = "brain-card";
    card.dataset.slug = brain.slug;
    card.innerHTML = `
      <div class="brain-card-header">
        <img class="brain-avatar" src="/images/${brain.slug}.svg" alt="" onerror="this.src='/images/default.svg'">
        <div>
          <div class="brain-card-name">${brain.display_name}</div>
          <div class="brain-card-tagline">${brain.tagline || ""}</div>
        </div>
        <div style="margin-left:auto;font-size:1.25rem;color:var(--purple);opacity:0" class="check-icon">✓</div>
      </div>
    `;
    card.addEventListener("click", () => toggleBrain(brain.slug, card));
    brainGrid.appendChild(card);
  }
}

function toggleBrain(slug, card) {
  if (selectedSlugs.has(slug)) {
    selectedSlugs.delete(slug);
    card.classList.remove("selected");
    card.querySelector(".check-icon").style.opacity = "0";
  } else {
    if (selectedSlugs.size >= 4) {
      showError("You can select up to 4 thinkers for a group session.");
      return;
    }
    selectedSlugs.add(slug);
    card.classList.add("selected");
    card.querySelector(".check-icon").style.opacity = "1";
  }
  updateSubmitState();
}

function updateSubmitState() {
  const count = selectedSlugs.size;
  selectedCount.textContent = count > 0 ? `${count} selected` : "";
  submitBtn.disabled = count < 2 || !questionInput.value.trim();
}

questionInput?.addEventListener("input", updateSubmitState);

submitBtn?.addEventListener("click", async () => {
  const question = questionInput.value.trim();
  if (!question || selectedSlugs.size < 2) return;

  submitBtn.disabled = true;
  showLoading(Array.from(selectedSlugs));

  try {
    const { session_id } = await startGroupChat(Array.from(selectedSlugs), question);
    pollForCompletion(session_id, Array.from(selectedSlugs));
  } catch (e) {
    hideLoading();
    submitBtn.disabled = false;
    showError(e.message);
  }
});

function showLoading(slugs) {
  loadingArea.classList.remove("hidden");
  resultsArea.classList.add("hidden");
  loadingArea.innerHTML = `
    <div style="text-align:center;padding:3rem 1rem">
      <div class="spinner spinner-lg" style="margin:0 auto 1.5rem"></div>
      <h3 style="margin-bottom:0.5rem">Convening the council…</h3>
      <p style="font-size:0.875rem">Your thinkers are deliberating. This takes about a minute.</p>
      <div style="display:flex;justify-content:center;gap:1rem;margin-top:1.5rem;flex-wrap:wrap">
        ${slugs.map(s => {
          const b = brains.find(x => x.slug === s);
          return `<div style="display:flex;flex-direction:column;align-items:center;gap:0.375rem">
            <img class="brain-avatar" src="/images/${s}.svg" alt="" onerror="this.src='/images/default.svg'">
            <span style="font-size:0.75rem;color:var(--text-muted)">${b?.display_name || s}</span>
          </div>`;
        }).join("")}
      </div>
    </div>
  `;
}

function hideLoading() {
  loadingArea.classList.add("hidden");
}

function pollForCompletion(sessionId, slugs) {
  let attempts = 0;
  pollInterval = setInterval(async () => {
    attempts++;
    if (attempts > 90) { // 3 min timeout
      clearInterval(pollInterval);
      hideLoading();
      showError("The session is taking longer than expected. Check your past sessions for results.");
      return;
    }
    try {
      const { status } = await getGroupSessionStatus(sessionId);
      if (status === "complete") {
        clearInterval(pollInterval);
        const session = await getGroupSession(sessionId);
        hideLoading();
        renderResults(session, slugs);
        loadPastSessions();
      } else if (status === "failed") {
        clearInterval(pollInterval);
        hideLoading();
        showError("The group session failed. Please try again.");
      }
    } catch (_) { /* retry */ }
  }, 2000);
}

function renderResults(session, slugs) {
  resultsArea.classList.remove("hidden");

  const round1 = session.responses.filter(r => r.round === 1);
  const round2 = session.responses.filter(r => r.round === 2);

  let html = `<h2 style="margin-bottom:1.5rem">Council results</h2>`;

  // Per-brain tabs
  html += `<div style="display:flex;gap:0.75rem;flex-wrap:wrap;margin-bottom:1.5rem">`;
  for (const slug of slugs) {
    const brain = brains.find(b => b.slug === slug);
    const r1 = round1.find(r => r.brain_slug === slug);
    const r2 = round2.find(r => r.brain_slug === slug);
    html += `
      <div class="card" style="flex:1;min-width:240px">
        <div class="brain-card-header" style="margin-bottom:1rem">
          <img class="brain-avatar" src="/images/${slug}.svg" alt="" onerror="this.src='/images/default.svg'">
          <strong>${brain?.display_name || slug}</strong>
        </div>
        <div style="margin-bottom:0.75rem">
          <div class="sidebar-label">Round 1</div>
          <p style="font-size:0.875rem;color:var(--text)">${r1?.content || "—"}</p>
        </div>
        ${r2 ? `<div><div class="sidebar-label">Round 2</div><p style="font-size:0.875rem;color:var(--text)">${r2.content}</p></div>` : ""}
      </div>
    `;
  }
  html += `</div>`;

  // Synthesis
  if (session.synthesis) {
    html += `
      <div class="card" style="border-color:var(--purple);background:var(--purple-dim)">
        <div class="sidebar-label" style="color:var(--gold);margin-bottom:0.75rem">✦ Synthesis</div>
        <p style="color:var(--text);line-height:1.75">${session.synthesis.content}</p>
      </div>
    `;
  }

  resultsArea.innerHTML = html;
  resultsArea.scrollIntoView({ behavior: "smooth" });
}

async function loadPastSessions() {
  try {
    const sessions = await getGroupSessions();
    if (!sessions.length) { sessionsList.innerHTML = '<p class="text-muted text-sm">No past sessions yet.</p>'; return; }
    sessionsList.innerHTML = sessions.slice(0, 10).map(s => `
      <div class="card card-sm" style="cursor:pointer" onclick="loadSession('${s.id}')">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:0.5rem">
          <p style="color:var(--text);font-size:0.875rem;flex:1">${s.question}</p>
          <span class="badge ${s.status === 'complete' ? 'badge-green' : s.status === 'failed' ? 'badge-red' : 'badge-purple'}">${s.status}</span>
        </div>
        <div class="text-xs text-muted mt-1">${new Date(s.created_at).toLocaleDateString()}</div>
      </div>
    `).join("");
  } catch (_) {}
}

window.loadSession = async function(id) {
  try {
    const session = await getGroupSession(id);
    renderResults(session, session.brain_slugs);
  } catch (e) {
    showError(e.message);
  }
};

function showError(msg) {
  const el = document.createElement("div");
  el.className = "alert alert-error";
  el.style.cssText = "position:fixed;bottom:1rem;right:1rem;z-index:300;max-width:340px";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

init().catch(console.error);
