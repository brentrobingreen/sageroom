import { getSession, signOut, signUp, signIn } from "./auth.js";
import {
  getBrains, getConversations, getMessages, deleteConversation,
  streamChat, getBillingStatus, getBillingPacks, purchaseCredits, apiFetch
} from "./api.js";

// ── State ────────────────────────────────────────────────────────────────────
let brains = [];
let conversations = [];
let activeBrainSlug = null;
let activeConversationId = null;
let abortStream = null;
let isStreaming = false;
let autoScroll = true;
let currentUser = null;
let authTab = "signup";

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
const emptyState     = document.getElementById("empty-state");
const authBottomBtn  = document.getElementById("auth-bottom-btn");
const accountLink    = document.getElementById("account-link");
const authModal      = document.getElementById("auth-modal");
const creditsOverlay = document.getElementById("credits-overlay");

// ── Init ─────────────────────────────────────────────────────────────────────
async function init() {
  const session = await getSession();
  currentUser = session?.user || null;

  await loadBrains();

  if (currentUser) {
    authBottomBtn.textContent = "Sign out";
    authBottomBtn.onclick = () => signOut();
    accountLink.style.display = "";
    await Promise.all([loadConversations()]);
    const saved = localStorage.getItem("sageroom_brain");
    if (saved && brains.find(b => b.slug === saved)) selectBrain(saved, false);
    else if (brains.length) selectBrain(brains[0].slug, false);
  } else {
    authBottomBtn.textContent = "Sign in / Sign up";
    authBottomBtn.onclick = () => openAuthModal("signup");
    accountLink.style.display = "none";
    // Still select first brain so layout looks alive
    if (brains.length) selectBrain(brains[0].slug, false);
  }

  setupScrollWatcher();
  if (currentUser) chatInput.focus();
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
    const el = document.createElement("button");
    el.className = "brain-chip";
    el.dataset.slug = brain.slug;
    el.innerHTML = `
      <img src="/images/${brain.slug}.svg" alt="" onerror="this.src='/images/default.svg'">
      <div class="brain-chip-info">
        <div class="brain-chip-name">${brain.display_name}</div>
        <div class="brain-chip-tagline">${brain.tagline || ""}</div>
      </div>
    `;
    el.addEventListener("click", () => {
      if (!currentUser) { openAuthModal("signup"); return; }
      selectBrain(brain.slug);
      closeSidebar();
    });
    brainList.appendChild(el);
  }
}

function selectBrain(slug, clearConversation = true) {
  activeBrainSlug = slug;
  localStorage.setItem("sageroom_brain", slug);

  // Apply brain colour theme
  document.querySelector(".chat-layout")?.setAttribute("data-brain", slug);

  document.querySelectorAll(".brain-chip").forEach(el =>
    el.classList.toggle("active", el.dataset.slug === slug));

  const brain = brains.find(b => b.slug === slug);
  if (brain) {
    topbarName.textContent = brain.display_name;
    topbarTagline.textContent = brain.tagline || "";
    topbarAvatar.src = `/images/${slug}.svg`;
    topbarAvatar.onerror = () => { topbarAvatar.src = "/images/default.svg"; };
  }

  if (clearConversation) {
    activeConversationId = null;
    if (messages) messages.innerHTML = "";
    showEmptyState(true);
  }

  if (currentUser) {
    renderConvList();
    sendBtn.disabled = false;
  } else {
    sendBtn.disabled = false; // still clickable — triggers auth modal
  }
  closeSidebar();
}

// ── Conversations ─────────────────────────────────────────────────────────────
async function loadConversations() {
  try {
    conversations = await getConversations();
    renderConvList();
  } catch (_) {}
}

function renderConvList() {
  convList.innerHTML = "";
  const filtered = conversations.filter(c => !activeBrainSlug || c.brain_slug === activeBrainSlug);
  if (!filtered.length) {
    convList.innerHTML = '<p class="text-xs text-muted" style="padding:0.5rem 0.625rem">No conversations yet.</p>';
    return;
  }
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
  document.querySelectorAll("#conv-list .sidebar-item").forEach(el =>
    el.classList.toggle("active", el.dataset.id === id));
  showEmptyState(false);
  messages.innerHTML = '<div class="spinner spinner-lg" style="margin:2rem auto"></div>';
  try {
    const msgs = await getMessages(id);
    messages.innerHTML = "";
    for (const m of msgs) appendMessage(m.role, m.content, false);
    scrollToBottom(true);
  } catch (e) { showError(e.message); }
}

// ── Messaging ─────────────────────────────────────────────────────────────────
async function sendMessage() {
  if (!currentUser) { openAuthModal("signup"); return; }
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
    if (isStreaming) { abortCurrentStream(); showBubbleError(aiBubble, "No response in 10 seconds. Please try again."); }
  }, 10000);

  abortStream = await streamChat({
    brainSlug: activeBrainSlug,
    message: text,
    conversationId: activeConversationId,
    onToken(token, convId) {
      clearTimeout(timeout);
      if (convId && !activeConversationId) { activeConversationId = convId; loadConversations(); }
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
      if (msg.includes("free messages") || msg.includes("credits")) showCreditsOverlay();
      else showBubbleError(aiBubble, msg);
      finishStream();
    },
  });
}

function finishStream() {
  isStreaming = false; abortStream = null;
  setInputEnabled(true); chatInput.focus();
}

function abortCurrentStream() {
  if (abortStream) { abortStream(); abortStream = null; }
  isStreaming = false; setInputEnabled(true);
}

// ── Auth modal ────────────────────────────────────────────────────────────────
function openAuthModal(tab = "signup") {
  authTab = tab;
  authModal.classList.remove("hidden");
  document.getElementById("tab-signup").classList.toggle("active", tab === "signup");
  document.getElementById("tab-signin").classList.toggle("active", tab === "signin");
  document.getElementById("auth-submit-btn").textContent = tab === "signup" ? "Create account" : "Sign in";
  document.getElementById("modal-title").textContent = tab === "signup" ? "Welcome to Sageroom" : "Sign in";
  document.getElementById("auth-error").classList.add("hidden");
  document.getElementById("auth-success").classList.add("hidden");
  setTimeout(() => document.getElementById("auth-email").focus(), 50);
}

window.switchTab = function(tab) {
  authTab = tab;
  document.getElementById("tab-signup").classList.toggle("active", tab === "signup");
  document.getElementById("tab-signin").classList.toggle("active", tab === "signin");
  document.getElementById("auth-submit-btn").textContent = tab === "signup" ? "Create account" : "Sign in";
  document.getElementById("modal-title").textContent = tab === "signup" ? "Welcome to Sageroom" : "Sign in";
  document.getElementById("auth-error").classList.add("hidden");
  document.getElementById("auth-success").classList.add("hidden");
};

document.getElementById("modal-close-btn").onclick = () => authModal.classList.add("hidden");
authModal.addEventListener("click", e => { if (e.target === authModal) authModal.classList.add("hidden"); });

document.getElementById("auth-submit-btn").onclick = async () => {
  const email = document.getElementById("auth-email").value.trim();
  const password = document.getElementById("auth-password").value;
  const errEl = document.getElementById("auth-error");
  const okEl = document.getElementById("auth-success");
  errEl.classList.add("hidden"); okEl.classList.add("hidden");
  const btn = document.getElementById("auth-submit-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner spinner-sm"></span>';
  try {
    if (authTab === "signup") {
      const result = await signUp(email, password);
      if (result.needsConfirmation) {
        okEl.textContent = "Check your inbox for a confirmation link, then sign in.";
        okEl.classList.remove("hidden");
        switchTab("signin");
      } else {
        window.location.reload();
      }
    } else {
      await signIn(email, password);
      window.location.reload();
    }
  } catch (e) {
    errEl.textContent = e.message;
    errEl.classList.remove("hidden");
  } finally {
    btn.disabled = false;
    btn.textContent = authTab === "signup" ? "Create account" : "Sign in";
  }
};

document.getElementById("auth-password").addEventListener("keydown", e => {
  if (e.key === "Enter") document.getElementById("auth-submit-btn").click();
});

// ── Credits overlay ───────────────────────────────────────────────────────────
async function showCreditsOverlay() {
  creditsOverlay.classList.remove("hidden");
  const packsEl = document.getElementById("credits-packs");
  packsEl.innerHTML = '<div class="spinner" style="margin:1rem auto"></div>';
  try {
    const packs = await getBillingPacks();
    packsEl.innerHTML = packs.map(p => `
      <button class="btn btn-primary btn-full" onclick="buyPack('${p.id}')">
        ${p.price_label} — ${p.credits} credits (${p.name})
      </button>
    `).join("");
  } catch (_) {
    packsEl.innerHTML = '<a href="/account.html" class="btn btn-primary btn-full">View account</a>';
  }
}

window.buyPack = async (packId) => { await purchaseCredits(packId); };

creditsOverlay.addEventListener("click", e => {
  if (e.target === creditsOverlay) creditsOverlay.classList.add("hidden");
});

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
  messages?.addEventListener("scroll", () => {
    autoScroll = messages.scrollHeight - messages.scrollTop - messages.clientHeight < 80;
  });
}

// ── UI helpers ─────────────────────────────────────────────────────────────────
function setInputEnabled(enabled) {
  chatInput.disabled = !enabled;
  sendBtn.disabled = !enabled;
  if (enabled) { sendBtn.innerHTML = "↑"; sendBtn.title = "Send"; sendBtn.onclick = null; }
  else { sendBtn.innerHTML = "■"; sendBtn.title = "Stop"; sendBtn.onclick = () => abortCurrentStream(); }
}

function showEmptyState(show) {
  emptyState?.classList.toggle("hidden", !show);
  if (messages) messages.style.display = show ? "none" : "flex";
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

// ── Input ─────────────────────────────────────────────────────────────────────
function resizeInput() {
  chatInput.style.height = "auto";
  chatInput.style.height = Math.min(chatInput.scrollHeight, 140) + "px";
}

chatInput?.addEventListener("input", resizeInput);
chatInput?.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); if (!isStreaming) sendMessage(); }
  if (e.key === "Escape" && isStreaming) abortCurrentStream();
});

sendBtn?.addEventListener("click", () => {
  if (isStreaming) abortCurrentStream();
  else sendMessage();
});

newChatBtn?.addEventListener("click", () => {
  activeConversationId = null;
  if (messages) messages.innerHTML = "";
  showEmptyState(true);
  chatInput.focus();
  closeSidebar();
});

// ── Boot ──────────────────────────────────────────────────────────────────────
init().catch(console.error);
