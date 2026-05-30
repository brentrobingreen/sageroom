import { requireAuth, signOut } from "./auth.js";
import {
  getBrains, getConversations, getMessages, deleteConversation, streamChat
} from "./api.js";

// ── State ────────────────────────────────────────────────────────────────────
let brains = [];
let conversations = [];
let activeBrainSlug = null;
let activeConversationId = null;
let abortStream = null;
let isStreaming = false;
let autoScroll = true;

// ── DOM refs ─────────────────────────────────────────────────────────────────
const sidebar        = document.getElementById("sidebar");
const sidebarOverlay = document.getElementById("sidebar-overlay");
const hamburger      = document.getElementById("hamburger");
const brainList      = document.getElementById("brain-list");
const convList       = document.getElementById("conv-list");
const newChatBtn     = document.getElementById("new-chat-btn");
const topbarAvatar   = document.getElementById("topbar-avatar");
const topbarName     = document.getElementById("topbar-name");
const topbarTagline  = document.getElementById("topbar-tagline");
const messages       = document.getElementById("messages");
const chatInput      = document.getElementById("chat-input");
const sendBtn        = document.getElementById("send-btn");
const paywallOverlay = document.getElementById("paywall-overlay");
const subscribeBtn   = document.getElementById("subscribe-btn");
const emptyState     = document.getElementById("empty-state");

// ── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  await requireAuth();
  await Promise.all([loadBrains(), loadConversations()]);

  const saved = localStorage.getItem("sageroom_brain");
  if (saved && brains.find(b => b.slug === saved)) {
    selectBrain(saved, false);
  } else if (brains.length) {
    selectBrain(brains[0].slug, false);
  }

  setupScrollWatcher();
  chatInput.focus();
}

// ── Brains ───────────────────────────────────────────────────────────────────
async function loadBrains() {
  try {
    brains = await getBrains();
    renderBrainList();
  } catch (e) {
    showError(e.message);
  }
}

function renderBrainList() {
  brainList.innerHTML = "";
  for (const brain of brains) {
    const el = document.createElement("div");
    el.className = "sidebar-item";
    el.dataset.slug = brain.slug;
    el.innerHTML = `
      <img class="brain-avatar" style="width:28px;height:28px" src="/images/${brain.slug}.svg" alt="" onerror="this.src='/images/default.svg'">
      <span>${brain.display_name}</span>
    `;
    el.addEventListener("click", () => { selectBrain(brain.slug); closeSidebar(); });
    brainList.appendChild(el);
  }
}

function selectBrain(slug, clearConversation = true) {
  activeBrainSlug = slug;
  localStorage.setItem("sageroom_brain", slug);

  document.querySelectorAll("#brain-list .sidebar-item").forEach(el => {
    el.classList.toggle("active", el.dataset.slug === slug);
  });

  const brain = brains.find(b => b.slug === slug);
  if (brain) {
    topbarName.textContent = brain.display_name;
    topbarTagline.textContent = brain.tagline || "";
    topbarAvatar.src = `/images/${slug}.svg`;
    topbarAvatar.onerror = () => { topbarAvatar.src = "/images/default.svg"; };
  }

  if (clearConversation) {
    activeConversationId = null;
    messages.innerHTML = "";
    showEmptyState(true);
  }
  closeSidebar();
}

// ── Conversations ─────────────────────────────────────────────────────────────
async function loadConversations() {
  try {
    conversations = await getConversations();
    renderConvList();
  } catch (_) { /* non-fatal */ }
}

function renderConvList() {
  convList.innerHTML = "";
  const filtered = conversations.filter(c => !activeBrainSlug || c.brain_slug === activeBrainSlug);
  for (const conv of filtered) {
    const el = document.createElement("div");
    el.className = "sidebar-item";
    el.dataset.id = conv.id;
    el.textContent = conv.title || "Conversation";
    el.style.cssText = "font-size:0.8125rem;white-space:nowrap;overflow:hidden;text-overflow:ellipsis";
    el.addEventListener("click", () => { selectConversation(conv.id); closeSidebar(); });
    convList.appendChild(el);
  }
}

async function selectConversation(id) {
  activeConversationId = id;
  document.querySelectorAll("#conv-list .sidebar-item").forEach(el => {
    el.classList.toggle("active", el.dataset.id === id);
  });

  showEmptyState(false);
  messages.innerHTML = '<div class="spinner spinner-lg" style="margin:2rem auto"></div>';

  try {
    const msgs = await getMessages(id);
    messages.innerHTML = "";
    for (const m of msgs) appendMessage(m.role, m.content, false);
    scrollToBottom(true);
  } catch (e) {
    showError(e.message);
  }
}

// ── Messaging ─────────────────────────────────────────────────────────────────
async function sendMessage() {
  if (isStreaming || !activeBrainSlug) return;
  const text = chatInput.value.trim();
  if (!text) return;

  chatInput.value = "";
  resizeInput();
  showEmptyState(false);
  appendMessage("user", text, false);
  scrollToBottom(true);

  const aiBubble = appendMessage("assistant", "", true);
  let buffer = "";

  isStreaming = true;
  setInputEnabled(false);

  const timeout = setTimeout(() => {
    if (isStreaming) {
      abortCurrentStream();
      showBubbleError(aiBubble, "No response in 10 seconds. Please try again.");
    }
  }, 10000);

  abortStream = await streamChat({
    brainSlug: activeBrainSlug,
    message: text,
    conversationId: activeConversationId,
    onToken(token, convId) {
      clearTimeout(timeout);
      if (convId && !activeConversationId) {
        activeConversationId = convId;
        loadConversations();
      }
      buffer += token;
      aiBubble.querySelector(".bubble-content").innerHTML = renderMarkdown(buffer);
      const cursor = aiBubble.querySelector(".typing-cursor");
      if (cursor) aiBubble.querySelector(".bubble-content").appendChild(cursor);
      if (autoScroll) scrollToBottom();
    },
    onDone(convId) {
      clearTimeout(timeout);
      if (convId) activeConversationId = convId;
      aiBubble.querySelector(".typing-cursor")?.remove();
      finishStream();
      loadConversations();
    },
    onError(msg) {
      clearTimeout(timeout);
      if (msg.includes("Subscribe")) showPaywall();
      else showBubbleError(aiBubble, msg);
      finishStream();
    },
  });
}

function finishStream() {
  isStreaming = false;
  abortStream = null;
  setInputEnabled(true);
  chatInput.focus();
}

function abortCurrentStream() {
  if (abortStream) { abortStream(); abortStream = null; }
  isStreaming = false;
  setInputEnabled(true);
}

// ── Render helpers ─────────────────────────────────────────────────────────────
function appendMessage(role, content, withCursor) {
  const wrap = document.createElement("div");
  wrap.className = `message ${role === "user" ? "message-user" : ""}`;

  if (role === "assistant") {
    const avatarSlug = activeBrainSlug || "default";
    wrap.innerHTML = `
      <img class="message-avatar" src="/images/${avatarSlug}.svg" alt="" onerror="this.src='/images/default.svg'">
      <div class="message-bubble-ai-wrap">
        <div class="message-bubble message-bubble-ai">
          <div class="bubble-content">${content ? renderMarkdown(content) : ""}</div>
          ${withCursor ? '<span class="typing-cursor"></span>' : ""}
        </div>
        <button class="copy-btn btn btn-sm" onclick="copyBubble(this)">Copy</button>
      </div>
    `;
  } else {
    const escaped = content.replace(/</g, "&lt;").replace(/>/g, "&gt;");
    wrap.innerHTML = `<div class="message-bubble message-bubble-user">${escaped}</div>`;
  }

  messages.appendChild(wrap);
  return wrap;
}

function showBubbleError(bubbleEl, msg) {
  const content = bubbleEl.querySelector(".bubble-content");
  if (content) content.innerHTML = `<span style="color:var(--red)">${msg}</span>`;
  bubbleEl.querySelector(".typing-cursor")?.remove();
}

function renderMarkdown(text) {
  return text
    .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
    .replace(/```([\s\S]*?)```/g, (_, c) => `<pre><code>${c.trim()}</code></pre>`)
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>")
    .replace(/\*([^*]+)\*/g, "<em>$1</em>")
    .replace(/^### (.+)$/gm, "<h4>$1</h4>")
    .replace(/^## (.+)$/gm, "<h3>$1</h3>")
    .replace(/^- (.+)$/gm, "<li>$1</li>")
    .replace(/(<li>.*<\/li>)/s, "<ul>$1</ul>")
    .replace(/^\d+\. (.+)$/gm, "<li>$1</li>")
    .replace(/\n{2,}/g, "</p><p>")
    .replace(/\n/g, "<br>")
    .replace(/^(?!<[hupol])(.+)/, "<p>$1</p>");
}

window.copyBubble = function(btn) {
  const text = btn.closest(".message-bubble-ai-wrap").querySelector(".bubble-content").innerText;
  navigator.clipboard.writeText(text).then(() => {
    btn.textContent = "Copied!";
    setTimeout(() => { btn.textContent = "Copy"; }, 2000);
  });
};

// ── Scroll ────────────────────────────────────────────────────────────────────
function scrollToBottom(force = false) {
  if (!autoScroll && !force) return;
  messages.scrollTop = messages.scrollHeight;
}

function setupScrollWatcher() {
  messages.addEventListener("scroll", () => {
    const atBottom = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80;
    autoScroll = atBottom;
  });
}

// ── UI helpers ─────────────────────────────────────────────────────────────────
function setInputEnabled(enabled) {
  chatInput.disabled = !enabled;
  sendBtn.disabled = !enabled;
  if (enabled) {
    sendBtn.innerHTML = "↑";
    sendBtn.title = "Send";
  } else {
    sendBtn.innerHTML = "■";
    sendBtn.title = "Stop";
    sendBtn.onclick = () => { abortCurrentStream(); };
  }
}

function showEmptyState(show) {
  emptyState?.classList.toggle("hidden", !show);
  messages.style.display = show ? "none" : "flex";
}

function showPaywall() {
  paywallOverlay?.classList.remove("hidden");
}

function showError(msg) {
  const el = document.createElement("div");
  el.className = "alert alert-error";
  el.style.cssText = "position:fixed;bottom:1rem;right:1rem;z-index:300;max-width:340px";
  el.textContent = msg;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), 5000);
}

// ── Sidebar mobile ────────────────────────────────────────────────────────────
function closeSidebar() {
  sidebar.classList.remove("open");
  sidebarOverlay.classList.remove("show");
}

hamburger?.addEventListener("click", () => {
  sidebar.classList.toggle("open");
  sidebarOverlay.classList.toggle("show");
});
sidebarOverlay?.addEventListener("click", closeSidebar);

// ── Input auto-resize & keyboard shortcuts ─────────────────────────────────────
function resizeInput() {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + "px";
}

chatInput?.addEventListener("input", resizeInput);
chatInput?.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) {
    e.preventDefault();
    if (!isStreaming) sendMessage();
  }
  if (e.key === "Escape" && isStreaming) abortCurrentStream();
});

sendBtn?.addEventListener("click", () => {
  if (isStreaming) abortCurrentStream();
  else sendMessage();
});

newChatBtn?.addEventListener("click", () => {
  activeConversationId = null;
  messages.innerHTML = "";
  showEmptyState(true);
  chatInput.focus();
  closeSidebar();
});

subscribeBtn?.addEventListener("click", async () => {
  const { startCheckout } = await import("./api.js");
  await startCheckout();
});

document.getElementById("signout-btn")?.addEventListener("click", async () => {
  const { signOut: so } = await import("./auth.js");
  await so();
});

// ── Boot ──────────────────────────────────────────────────────────────────────
init().catch(console.error);
