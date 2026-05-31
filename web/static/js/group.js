import { requireAuth, setupSessionMonitor } from "./auth.js";
import { getBrains, getGroupSessions, getGroupSession, apiFetch, getToken } from "./api.js";

// ── State ─────────────────────────────────────────────────────────────────────
let brains = [];
let selectedSlugs = new Set();
let sessionId = null;
let sessionBrainSlugs = [];
let contextRound = 0;
let followUpCount = 0;

// ── DOM ───────────────────────────────────────────────────────────────────────
const phaseSetup       = document.getElementById("phase-setup");
const phaseContext     = document.getElementById("phase-context");
const phaseDeliberating = document.getElementById("phase-deliberating");
const phaseResults     = document.getElementById("phase-results");

const brainGrid        = document.getElementById("brain-grid");
const openingQ         = document.getElementById("opening-question");
const conveneBtn       = document.getElementById("convene-btn");
const selectedCount    = document.getElementById("selected-count");
const sessionsList     = document.getElementById("sessions-list");

const contextAvatars   = document.getElementById("context-avatars");
const contextQuestion  = document.getElementById("context-question");
const contextAnswer    = document.getElementById("context-answer");
const contextSubmitBtn = document.getElementById("context-submit-btn");
const contextSkipBtn   = document.getElementById("context-skip-btn");
const contextProgress  = document.getElementById("context-progress");

const deliberatingAvatars = document.getElementById("deliberating-avatars");
const resultsAvatars   = document.getElementById("results-avatars");
const resultsQuestion  = document.getElementById("results-question");
const perspectivesArea = document.getElementById("perspectives-area");
const followUpRounds   = document.getElementById("followup-rounds");
const synthesisArea    = document.getElementById("synthesis-area");
const synthesisContent = document.getElementById("synthesis-content");
const followupArea     = document.getElementById("followup-area");
const followupInput    = document.getElementById("followup-input");
const followupBtn      = document.getElementById("followup-btn");
const newSessionBtn    = document.getElementById("new-session-btn");

// ── Init ──────────────────────────────────────────────────────────────────────
async function init() {
  await requireAuth();
  await setupSessionMonitor();
  await Promise.all([loadBrains(), loadPastSessions()]);
}

async function loadBrains() {
  try {
    brains = await getBrains();
    renderBrainGrid();
  } catch (e) { showToast(e.message); }
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
        <div class="check-icon" style="margin-left:auto;font-size:1.125rem;color:var(--purple);opacity:0">✓</div>
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
    if (selectedSlugs.size >= 4) { showToast("Maximum 4 thinkers per session."); return; }
    selectedSlugs.add(slug);
    card.classList.add("selected");
    card.querySelector(".check-icon").style.opacity = "1";
  }
  updateConveneState();
}

function updateConveneState() {
  const n = selectedSlugs.size;
  selectedCount.textContent = n > 0 ? `${n} selected` : "";
  conveneBtn.disabled = n < 2 || !openingQ.value.trim();
}

openingQ.addEventListener("input", updateConveneState);

// ── Convene ───────────────────────────────────────────────────────────────────
conveneBtn.addEventListener("click", async () => {
  const question = openingQ.value.trim();
  if (selectedSlugs.size < 2 || !question) return;

  conveneBtn.disabled = true;
  conveneBtn.innerHTML = '<span class="spinner spinner-sm"></span>';

  try {
    const slugs = Array.from(selectedSlugs);
    const result = await apiFetch("/api/group-chat", {
      method: "POST",
      body: JSON.stringify({ brain_slugs: slugs, question }),
    });

    sessionId = result.session_id;
    sessionBrainSlugs = slugs;
    contextRound = 0;

    if (result.ready) {
      showDeliberating(question, slugs);
      await runDeliberation();
    } else {
      showContext(result.question, slugs, 1);
    }
  } catch (e) {
    showToast(e.message);
    conveneBtn.disabled = false;
    conveneBtn.textContent = "Convene ✦";
  }
});

// ── Context phase ─────────────────────────────────────────────────────────────
function showContext(question, slugs, round) {
  contextRound = round;
  contextQuestion.textContent = question;
  contextAnswer.value = "";
  contextSubmitBtn.disabled = true;
  contextProgress.textContent = `Context question ${round} of 2`;

  contextAvatars.innerHTML = slugs.map(s => `
    <img style="width:40px;height:40px;border-radius:50%;background:var(--purple-muted)"
      src="/images/${s}.svg" onerror="this.src='/images/default.svg'" alt="">
  `).join("");

  showPhase("context");
  setTimeout(() => contextAnswer.focus(), 100);
}

contextAnswer.addEventListener("input", () => {
  contextSubmitBtn.disabled = !contextAnswer.value.trim();
});

contextSubmitBtn.addEventListener("click", () => submitContextAnswer());
contextSkipBtn.addEventListener("click", () => submitContextAnswer(true));
contextAnswer.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey && contextAnswer.value.trim()) {
    e.preventDefault();
    submitContextAnswer();
  }
});

async function submitContextAnswer(skip = false) {
  const answer = skip ? "(skipped)" : contextAnswer.value.trim();
  contextSubmitBtn.disabled = true;
  contextSubmitBtn.innerHTML = '<span class="spinner spinner-sm"></span>';

  try {
    const result = await apiFetch(`/api/group-chat/${sessionId}/context`, {
      method: "POST",
      body: JSON.stringify({ answer }),
    });

    if (result.ready) {
      const question = openingQ.value.trim();
      showDeliberating(question, sessionBrainSlugs);
      await runDeliberation();
    } else {
      showContext(result.question, sessionBrainSlugs, contextRound + 1);
    }
  } catch (e) {
    showToast(e.message);
    contextSubmitBtn.disabled = false;
    contextSubmitBtn.textContent = "Continue ✦";
  }
}

// ── Deliberation ──────────────────────────────────────────────────────────────
function showDeliberating(question, slugs) {
  deliberatingAvatars.innerHTML = slugs.map(s => `
    <img style="width:48px;height:48px;border-radius:50%;background:var(--purple-muted)"
      src="/images/${s}.svg" onerror="this.src='/images/default.svg'" alt="">
  `).join("");
  showPhase("deliberating");
}

async function runDeliberation(isFollowUp = false, followUpQuestion = "") {
  const endpoint = isFollowUp
    ? `/api/group-chat/${sessionId}/followup`
    : `/api/group-chat/${sessionId}/deliberate`;
  const body = isFollowUp ? JSON.stringify({ question: followUpQuestion }) : undefined;
  const method = "POST";

  if (!isFollowUp) {
    // Prepare results view
    perspectivesArea.innerHTML = "";
    followUpRounds.innerHTML = "";
    synthesisArea.classList.add("hidden");
    synthesisContent.innerHTML = "";
    followupArea.classList.add("hidden");

    const question = openingQ.value.trim();
    resultsQuestion.textContent = `"${question}"`;
    resultsAvatars.innerHTML = sessionBrainSlugs.map(s => `
      <img style="width:28px;height:28px;border-radius:50%;background:var(--purple-muted)"
        src="/images/${s}.svg" onerror="this.src='/images/default.svg'" alt="">
    `).join("");

    // Create empty perspective cards upfront
    for (const slug of sessionBrainSlugs) {
      perspectivesArea.appendChild(makePerspectiveCard(slug));
    }
  } else {
    // Follow-up: add a new round section
    followUpCount++;
    const roundEl = document.createElement("div");
    roundEl.id = `followup-round-${followUpCount}`;
    roundEl.innerHTML = `
      <div style="display:flex;align-items:center;gap:0.75rem;margin:2rem 0 1rem">
        <div style="flex:1;height:1px;background:var(--border-subtle)"></div>
        <span class="text-xs text-muted">Follow-up: "${followUpQuestion}"</span>
        <div style="flex:1;height:1px;background:var(--border-subtle)"></div>
      </div>
      <div class="followup-perspectives" style="display:flex;flex-direction:column;gap:1rem;margin-bottom:1rem"></div>
      <div class="followup-synthesis hidden card synthesis-doc" style="margin-bottom:1rem"></div>
    `;
    followUpRounds.appendChild(roundEl);

    const perspContainer = roundEl.querySelector(".followup-perspectives");
    for (const slug of sessionBrainSlugs) {
      perspContainer.appendChild(makePerspectiveCard(slug, `followup-${followUpCount}-`));
    }

    // Reset synthesis area for this follow-up
    synthesisArea.classList.add("hidden");
    synthesisContent.innerHTML = "";

    showPhase("results"); // ensure results visible
    roundEl.scrollIntoView({ behavior: "smooth" });
  }

  const token = await getToken();
  let res;
  try {
    res = await fetch(endpoint, {
      method,
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body,
    });
  } catch {
    showToast("Connection failed. Please try again.");
    if (!isFollowUp) showPhase("setup");
    return;
  }

  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    showToast(err.detail || "Something went wrong.");
    if (!isFollowUp) showPhase("setup");
    return;
  }

  showPhase("results");

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let synthBuf = "";
  let inSynthesis = false;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buf += decoder.decode(value, { stream: true });
    const lines = buf.split("\n");
    buf = lines.pop();

    for (const line of lines) {
      if (!line.startsWith("data: ")) continue;
      try {
        const data = JSON.parse(line.slice(6));

        if (data.type === "brain_start") {
          activateCard(data.brain_slug, isFollowUp);
        } else if (data.type === "token") {
          appendToCard(data.brain_slug, data.text, isFollowUp);
        } else if (data.type === "brain_done") {
          finalizeCard(data.brain_slug, isFollowUp);
        } else if (data.type === "synthesis_start") {
          inSynthesis = true;
          synthBuf = "";
          if (isFollowUp) {
            const roundEl = document.getElementById(`followup-round-${followUpCount}`);
            const synthEl = roundEl?.querySelector(".followup-synthesis");
            if (synthEl) synthEl.classList.remove("hidden");
          } else {
            synthesisArea.classList.remove("hidden");
          }
        } else if (data.type === "synthesis_token") {
          synthBuf += data.text;
          const target = isFollowUp
            ? document.getElementById(`followup-round-${followUpCount}`)?.querySelector(".followup-synthesis")
            : synthesisContent;
          if (target) target.innerHTML = renderMarkdown(synthBuf);
        } else if (data.type === "synthesis_done") {
          inSynthesis = false;
          followupArea.classList.remove("hidden");
          followupInput.value = "";
          followupBtn.disabled = false;
          followupBtn.textContent = "Ask ✦";
          if (!isFollowUp) synthesisArea.scrollIntoView({ behavior: "smooth", block: "start" });
        } else if (data.type === "all_done") {
          loadPastSessions();
        }
      } catch (_) {}
    }
  }
}

// ── Perspective cards ─────────────────────────────────────────────────────────
function makePerspectiveCard(slug, prefix = "") {
  const brain = brains.find(b => b.slug === slug);
  const el = document.createElement("div");
  el.className = "card";
  el.id = `${prefix}card-${slug}`;
  el.style.cssText = "opacity:0.4;transition:opacity 0.3s";
  el.innerHTML = `
    <div style="display:flex;align-items:center;gap:0.875rem;margin-bottom:0.875rem">
      <img style="width:40px;height:40px;border-radius:50%;background:var(--purple-muted);flex-shrink:0"
        src="/images/${slug}.svg" alt="" onerror="this.src='/images/default.svg'">
      <div>
        <div style="font-weight:600">${brain?.display_name || slug}</div>
        <div class="text-xs text-muted">${brain?.tagline || ""}</div>
      </div>
    </div>
    <div class="card-body" style="color:var(--text);line-height:1.75;font-size:0.9375rem">
      <div class="brain-thinking" style="color:var(--text-muted);font-size:0.875rem">
        <div class="spinner spinner-sm"></div> <span>Deliberating…</span>
      </div>
      <div class="card-text" style="display:none"></div>
    </div>
  `;
  return el;
}

function activateCard(slug, isFollowUp) {
  const prefix = isFollowUp ? `followup-${followUpCount}-` : "";
  const card = document.getElementById(`${prefix}card-${slug}`);
  if (!card) return;
  card.style.opacity = "1";
  card.querySelector(".brain-thinking").style.display = "none";
  card.querySelector(".card-text").style.display = "block";
}

function appendToCard(slug, text, isFollowUp) {
  const prefix = isFollowUp ? `followup-${followUpCount}-` : "";
  const card = document.getElementById(`${prefix}card-${slug}`);
  if (!card) return;
  const el = card.querySelector(".card-text");
  el.textContent += text;
}

function finalizeCard(slug, isFollowUp) {
  const prefix = isFollowUp ? `followup-${followUpCount}-` : "";
  const card = document.getElementById(`${prefix}card-${slug}`);
  if (!card) return;
  const el = card.querySelector(".card-text");
  el.innerHTML = renderMarkdown(el.textContent);
}

// ── Follow-up ─────────────────────────────────────────────────────────────────
followupBtn.addEventListener("click", async () => {
  const q = followupInput.value.trim();
  if (!q) return;
  followupBtn.disabled = true;
  followupBtn.innerHTML = '<span class="spinner spinner-sm"></span>';
  await runDeliberation(true, q);
});

followupInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey && followupInput.value.trim()) {
    e.preventDefault();
    followupBtn.click();
  }
});

// ── Past sessions ─────────────────────────────────────────────────────────────
async function loadPastSessions() {
  try {
    const sessions = await getGroupSessions();
    if (!sessions.length) {
      sessionsList.innerHTML = '<p class="text-muted text-sm">No past sessions yet.</p>';
      return;
    }
    sessionsList.innerHTML = sessions.slice(0, 6).map(s => `
      <div class="card card-sm" style="cursor:pointer" onclick="resumeSession('${s.id}', ${JSON.stringify(s.brain_slugs)}, ${JSON.stringify(s.question)})">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:0.5rem">
          <p style="color:var(--text);font-size:0.875rem;flex:1">${s.question}</p>
          <span class="badge ${s.status === 'synthesized' ? 'badge-gold' : 'badge-purple'}">${s.status}</span>
        </div>
        <div style="display:flex;align-items:center;gap:0.5rem;margin-top:0.5rem">
          ${(s.brain_slugs || []).map(slug => `<img style="width:20px;height:20px;border-radius:50%" src="/images/${slug}.svg" onerror="this.src='/images/default.svg'" alt="">`).join("")}
          <span class="text-xs text-muted">${new Date(s.created_at).toLocaleDateString()}</span>
        </div>
      </div>
    `).join("");
  } catch (_) {}
}

window.resumeSession = async function(id, slugs, question) {
  try {
    const session = await getGroupSession(id);
    sessionId = id;
    sessionBrainSlugs = slugs;
    followUpCount = 0;

    perspectivesArea.innerHTML = "";
    followUpRounds.innerHTML = "";
    synthesisArea.classList.add("hidden");
    synthesisContent.innerHTML = "";
    followupArea.classList.add("hidden");

    resultsQuestion.textContent = `"${question}"`;
    resultsAvatars.innerHTML = slugs.map(s => `
      <img style="width:28px;height:28px;border-radius:50%" src="/images/${s}.svg" onerror="this.src='/images/default.svg'" alt="">
    `).join("");

    // Group messages by turn and role
    const msgs = session.messages || [];
    const turns: Record<number, any> = {};
    for (const m of msgs) {
      if (m.brain_slug === "facilitator" || (!m.brain_slug && m.role === "user")) continue;
      const t = m.turn;
      if (!turns[t]) turns[t] = {};
      if (m.role === "assistant" && m.brain_slug) turns[t][m.brain_slug] = m.content;
    }

    const turnNums = Object.keys(turns).map(Number).sort((a, b) => a - b);
    const [firstTurn, ...restTurns] = turnNums;

    if (firstTurn !== undefined) {
      for (const slug of slugs) {
        const card = makePerspectiveCard(slug);
        card.style.opacity = "1";
        card.querySelector(".brain-thinking").style.display = "none";
        const textEl = card.querySelector(".card-text");
        textEl.style.display = "block";
        if (turns[firstTurn]?.[slug]) textEl.innerHTML = renderMarkdown(turns[firstTurn][slug]);
        perspectivesArea.appendChild(card);
      }
    }

    for (let i = 0; i < restTurns.length; i++) {
      const t = restTurns[i];
      followUpCount++;
      const roundEl = document.createElement("div");
      roundEl.id = `followup-round-${followUpCount}`;
      const followUpQ = msgs.find(m => m.turn === t && m.role === "user" && !m.brain_slug)?.content || "Follow-up";
      roundEl.innerHTML = `
        <div style="display:flex;align-items:center;gap:0.75rem;margin:2rem 0 1rem">
          <div style="flex:1;height:1px;background:var(--border-subtle)"></div>
          <span class="text-xs text-muted">Follow-up: "${followUpQ}"</span>
          <div style="flex:1;height:1px;background:var(--border-subtle)"></div>
        </div>
        <div class="followup-perspectives" style="display:flex;flex-direction:column;gap:1rem;margin-bottom:1rem"></div>
      `;
      const perspContainer = roundEl.querySelector(".followup-perspectives");
      for (const slug of slugs) {
        const card = makePerspectiveCard(slug, `followup-${followUpCount}-`);
        card.style.opacity = "1";
        card.querySelector(".brain-thinking").style.display = "none";
        const textEl = card.querySelector(".card-text");
        textEl.style.display = "block";
        if (turns[t]?.[slug]) textEl.innerHTML = renderMarkdown(turns[t][slug]);
        perspContainer.appendChild(card);
      }
      followUpRounds.appendChild(roundEl);
    }

    if (session.synthesis) {
      synthesisContent.innerHTML = renderMarkdown(session.synthesis.content);
      synthesisArea.classList.remove("hidden");
    }

    followupArea.classList.remove("hidden");
    showPhase("results");
  } catch (e) {
    showToast(e.message);
  }
};

newSessionBtn.addEventListener("click", () => {
  sessionId = null;
  sessionBrainSlugs = [];
  followUpCount = 0;
  selectedSlugs.clear();
  openingQ.value = "";
  updateConveneState();
  document.querySelectorAll("#brain-grid .brain-card").forEach(c => {
    c.classList.remove("selected");
    c.querySelector(".check-icon").style.opacity = "0";
  });
  conveneBtn.textContent = "Convene ✦";
  showPhase("setup");
  loadPastSessions();
});

// ── Phase transitions ─────────────────────────────────────────────────────────
function showPhase(name) {
  phaseSetup.classList.toggle("hidden", name !== "setup");
  phaseContext.classList.toggle("hidden", name !== "context");
  phaseDeliberating.classList.toggle("hidden", name !== "deliberating");
  phaseResults.classList.toggle("hidden", name !== "results");
}

// ── Markdown renderer ─────────────────────────────────────────────────────────
function renderMarkdown(text) {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/```([\s\S]*?)```/g, (_, c) => `<pre><code>${c.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/^## (.+)$/gm, "<h3>$1</h3>")
    .replace(/^### (.+)$/gm, "<h4>$1</h4>")
    .replace(/^\d+\. (.+)$/gm, "<li class=\"ol\">$1</li>")
    .replace(/^[-•] (.+)$/gm, "<li>$1</li>")
    .replace(/((?:<li class="ol">.*?<\/li>\n?)+)/gs, "<ol>$1</ol>")
    .replace(/((?:<li>(?!.*class=).*?<\/li>\n?)+)/gs, "<ul>$1</ul>")
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/\n/g, "<br>")
    .replace(/^(?!<[hupol])(.+)/m, "<p>$1</p>");
}

function showToast(msg) {
  const el = document.createElement("div");
  el.className = "alert alert-error";
  el.style.cssText = "position:fixed;bottom:1rem;right:1rem;z-index:300;max-width:340px";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

init().catch(console.error);
