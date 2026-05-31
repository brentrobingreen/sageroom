import { requireAuth, setupSessionMonitor } from "./auth.js";
import { getBrains, getGroupSessions, getGroupSession, apiFetch, getToken } from "./api.js";

// ── State ─────────────────────────────────────────────────────────────────────
let brains = [];
let selectedSlugs = new Set();
let sessionId = null;
let sessionBrainSlugs = [];
let turnCount = 0;
let isStreaming = false;

// ── DOM ───────────────────────────────────────────────────────────────────────
const setupView      = document.getElementById("setup-view");
const chatView       = document.getElementById("chat-view");
const brainGrid      = document.getElementById("brain-grid");
const openingQ       = document.getElementById("opening-question");
const conveneBtn     = document.getElementById("convene-btn");
const selectedCount  = document.getElementById("selected-count");
const topbarBrains   = document.getElementById("topbar-brains");
const groupMessages  = document.getElementById("group-messages");
const messagesInner  = document.getElementById("group-messages-inner");
const groupInput     = document.getElementById("group-input");
const groupSendBtn   = document.getElementById("group-send-btn");
const synthesizeBtn  = document.getElementById("synthesize-btn");
const newCouncilBtn  = document.getElementById("new-council-btn");
const sessionsList   = document.getElementById("sessions-list");
const synthesisModal = document.getElementById("synthesis-modal");
const synthesisClose = document.getElementById("synthesis-close");
const synthesisLoading = document.getElementById("synthesis-loading");
const synthesisContent = document.getElementById("synthesis-content");

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
  } catch (e) {
    showToast(e.message);
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

// ── Session start ─────────────────────────────────────────────────────────────
conveneBtn.addEventListener("click", async () => {
  const question = openingQ.value.trim();
  if (selectedSlugs.size < 2 || !question) return;

  conveneBtn.disabled = true;
  conveneBtn.innerHTML = '<span class="spinner spinner-sm"></span>';

  try {
    const slugs = Array.from(selectedSlugs);
    const { session_id } = await apiFetch("/api/group-chat", {
      method: "POST",
      body: JSON.stringify({ brain_slugs: slugs, question }),
    });
    sessionId = session_id;
    sessionBrainSlugs = slugs;
    showChatView(slugs);
    await sendMessage(question, true);
  } catch (e) {
    showToast(e.message);
    conveneBtn.disabled = false;
    conveneBtn.textContent = "Convene the council ✦";
  }
});

// ── Chat view ─────────────────────────────────────────────────────────────────
function showChatView(slugs) {
  setupView.classList.add("hidden");
  chatView.classList.remove("hidden");

  topbarBrains.innerHTML = slugs.map(s => {
    const brain = brains.find(b => b.slug === s);
    return `
      <div style="display:flex;align-items:center;gap:0.375rem;padding:0.25rem 0.625rem;border-radius:999px;background:var(--bg-elevated);font-size:0.8125rem;font-weight:500">
        <img style="width:20px;height:20px;border-radius:50%;object-fit:cover;background:var(--purple-muted)"
          src="/images/${s}.svg" alt="" onerror="this.src='/images/default.svg'">
        ${brain?.display_name || s}
      </div>`;
  }).join("");
}

newCouncilBtn.addEventListener("click", () => {
  sessionId = null;
  sessionBrainSlugs = [];
  turnCount = 0;
  messagesInner.innerHTML = "";
  selectedSlugs.clear();
  openingQ.value = "";
  updateConveneState();
  document.querySelectorAll("#brain-grid .brain-card").forEach(c => {
    c.classList.remove("selected");
    c.querySelector(".check-icon").style.opacity = "0";
  });
  chatView.classList.add("hidden");
  setupView.classList.remove("hidden");
  synthesizeBtn.disabled = true;
  conveneBtn.textContent = "Convene the council ✦";
  loadPastSessions();
});

// ── Messaging ─────────────────────────────────────────────────────────────────
async function sendMessage(message, isOpening = false) {
  if (isStreaming) return;

  if (!isOpening) {
    groupInput.value = "";
    resizeInput();
  }

  appendUserMessage(message);
  scrollToBottom();

  const brainBubbles = {};
  for (const slug of sessionBrainSlugs) {
    brainBubbles[slug] = appendBrainBubble(slug);
  }
  scrollToBottom();

  isStreaming = true;
  setInputEnabled(false);

  try {
    const token = await getToken();
    const res = await fetch(`/api/group-chat/${sessionId}/message`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Authorization: `Bearer ${token}` },
      body: JSON.stringify({ message }),
    });

    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      showToast(body.detail || "Something went wrong.");
      removeBrainBubbles(brainBubbles);
      return;
    }

    const reader = res.body.getReader();
    const decoder = new TextDecoder();
    let buf = "";

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
            activateBrainBubble(brainBubbles[data.brain_slug]);
          } else if (data.type === "token") {
            appendToBrainBubble(brainBubbles[data.brain_slug], data.text);
            scrollToBottom();
          } else if (data.type === "brain_done") {
            finalizeBrainBubble(brainBubbles[data.brain_slug]);
          } else if (data.type === "brain_error") {
            showBrainError(brainBubbles[data.brain_slug]);
          } else if (data.type === "all_done") {
            turnCount = data.turn;
          }
        } catch (_) {}
      }
    }
  } catch (e) {
    showToast("Stream interrupted. Please try again.");
    removeBrainBubbles(brainBubbles);
  } finally {
    isStreaming = false;
    setInputEnabled(true);
    synthesizeBtn.disabled = false;
    scrollToBottom();
  }
}

// ── Message rendering ─────────────────────────────────────────────────────────
function appendUserMessage(text) {
  const el = document.createElement("div");
  el.className = "message message-user";
  const escaped = text.replace(/</g, "&lt;").replace(/>/g, "&gt;");
  el.innerHTML = `<div class="message-bubble message-bubble-user">${escaped}</div>`;
  messagesInner.appendChild(el);
}

function appendBrainBubble(slug) {
  const brain = brains.find(b => b.slug === slug);
  const wrap = document.createElement("div");
  wrap.className = "message group-brain-msg";
  wrap.dataset.slug = slug;
  wrap.innerHTML = `
    <img class="message-avatar" src="/images/${slug}.svg" alt="" onerror="this.src='/images/default.svg'">
    <div style="flex:1;min-width:0">
      <div class="group-brain-name">${brain?.display_name || slug}</div>
      <div class="message-bubble message-bubble-ai">
        <div class="brain-thinking">
          <div class="spinner spinner-sm"></div>
          <span>Thinking…</span>
        </div>
        <div class="bubble-content" style="display:none"></div>
      </div>
    </div>
  `;
  messagesInner.appendChild(wrap);
  return wrap;
}

function activateBrainBubble(wrap) {
  if (!wrap) return;
  wrap.querySelector(".brain-thinking").style.display = "none";
  wrap.querySelector(".bubble-content").style.display = "block";
}

function appendToBrainBubble(wrap, text) {
  if (!wrap) return;
  const content = wrap.querySelector(".bubble-content");
  content.textContent += text;
}

function finalizeBrainBubble(wrap) {
  if (!wrap) return;
  const content = wrap.querySelector(".bubble-content");
  const raw = content.textContent;
  content.innerHTML = renderMarkdown(raw);
}

function showBrainError(wrap) {
  if (!wrap) return;
  wrap.querySelector(".brain-thinking").style.display = "none";
  const content = wrap.querySelector(".bubble-content");
  content.style.display = "block";
  content.innerHTML = `<span style="color:var(--red)">Something went wrong. Please try again.</span>`;
}

function removeBrainBubbles(brainBubbles) {
  Object.values(brainBubbles).forEach(el => el?.remove());
}

// ── Synthesize ────────────────────────────────────────────────────────────────
synthesizeBtn.addEventListener("click", async () => {
  if (!sessionId) return;
  synthesisModal.classList.remove("hidden");
  synthesisLoading.style.display = "flex";
  synthesisContent.classList.add("hidden");
  synthesisContent.innerHTML = "";

  try {
    const { content } = await apiFetch(`/api/group-chat/${sessionId}/synthesize`, { method: "POST" });
    synthesisContent.innerHTML = renderMarkdown(content);
    synthesisLoading.style.display = "none";
    synthesisContent.classList.remove("hidden");
  } catch (e) {
    synthesisLoading.style.display = "none";
    synthesisContent.innerHTML = `<p style="color:var(--red)">${e.message}</p>`;
    synthesisContent.classList.remove("hidden");
  }
});

synthesisClose.addEventListener("click", () => synthesisModal.classList.add("hidden"));
synthesisModal.addEventListener("click", e => { if (e.target === synthesisModal) synthesisModal.classList.add("hidden"); });

// ── Past sessions ─────────────────────────────────────────────────────────────
async function loadPastSessions() {
  try {
    const sessions = await getGroupSessions();
    if (!sessions.length) {
      sessionsList.innerHTML = '<p class="text-muted text-sm">No past sessions yet.</p>';
      return;
    }
    sessionsList.innerHTML = sessions.slice(0, 8).map(s => `
      <div class="card card-sm" style="cursor:pointer" onclick="resumeSession('${s.id}', ${JSON.stringify(s.brain_slugs)})">
        <div style="display:flex;justify-content:space-between;align-items:flex-start;gap:0.5rem">
          <p style="color:var(--text);font-size:0.875rem;flex:1">${s.question}</p>
          <span class="badge ${s.status === 'synthesized' ? 'badge-gold' : s.status === 'active' ? 'badge-green' : 'badge-purple'}">${s.status}</span>
        </div>
        <div style="display:flex;align-items:center;gap:0.5rem;margin-top:0.5rem">
          ${(s.brain_slugs || []).map(slug => `<img style="width:20px;height:20px;border-radius:50%;background:var(--purple-muted)" src="/images/${slug}.svg" onerror="this.src='/images/default.svg'" alt="">`).join("")}
          <span class="text-xs text-muted">${new Date(s.created_at).toLocaleDateString()}</span>
        </div>
      </div>
    `).join("");
  } catch (_) {}
}

window.resumeSession = async function(id, slugs) {
  try {
    const session = await getGroupSession(id);
    sessionId = id;
    sessionBrainSlugs = slugs;
    messagesInner.innerHTML = "";
    showChatView(slugs);

    for (const msg of (session.messages || [])) {
      if (msg.role === "user") {
        appendUserMessage(msg.content);
      } else {
        const wrap = appendBrainBubble(msg.brain_slug);
        activateBrainBubble(wrap);
        const content = wrap.querySelector(".bubble-content");
        content.innerHTML = renderMarkdown(msg.content);
      }
    }

    if (session.synthesis) {
      synthesizeBtn.disabled = false;
    } else if ((session.messages || []).length > 0) {
      synthesizeBtn.disabled = false;
    }

    setInputEnabled(true);
    scrollToBottom(true);
  } catch (e) {
    showToast(e.message);
  }
};

// ── Utilities ─────────────────────────────────────────────────────────────────
function setInputEnabled(enabled) {
  groupInput.disabled = !enabled;
  groupSendBtn.disabled = !enabled;
}

function scrollToBottom(force = false) {
  groupMessages.scrollTop = groupMessages.scrollHeight;
}

function resizeInput() {
  groupInput.style.height = "auto";
  groupInput.style.height = Math.min(groupInput.scrollHeight, 140) + "px";
}

groupInput.addEventListener("input", resizeInput);
groupInput.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    const msg = groupInput.value.trim();
    if (msg && !isStreaming) sendMessage(msg);
  }
});

groupSendBtn.addEventListener("click", () => {
  const msg = groupInput.value.trim();
  if (msg && !isStreaming) sendMessage(msg);
});

function renderMarkdown(text) {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/```([\s\S]*?)```/g, (_, c) => `<pre><code>${c.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/^## (.+)$/gm, "<h3>$1</h3>")
    .replace(/^### (.+)$/gm, "<h4>$1</h4>")
    .replace(/^\d+\. (.+)$/gm, "<li class=\"ordered\">$1</li>")
    .replace(/^[-•] (.+)$/gm, "<li>$1</li>")
    .replace(/((?:<li class="ordered">.*<\/li>\n?)+)/gs, "<ol>$1</ol>")
    .replace(/((?:<li>(?!.*class="ordered").*<\/li>\n?)+)/gs, "<ul>$1</ul>")
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
