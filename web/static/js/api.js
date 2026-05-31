/* Sageroom — API client
   All requests go through apiFetch which handles auth, 401, and 429.
*/

import { getToken, signOut } from "./auth.js";

export { getToken };

export async function apiFetch(path, options = {}) {
  const token = await getToken();
  const headers = {
    "Content-Type": "application/json",
    ...(token ? { Authorization: `Bearer ${token}` } : {}),
    ...options.headers,
  };

  const res = await fetch(path, { ...options, headers });

  if (res.status === 401) {
    if (token) {
      // Had a token but server rejected it — session expired, force re-login
      await signOut();
    }
    throw new Error("Session expired. Please sign in again.");
  }

  if (res.status === 429) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || "You've hit a usage limit. Please wait a moment and try again.");
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${res.status}).`);
  }

  if (res.status === 204) return null;
  return res.json();
}

// ── Brains ──────────────────────────────────────────────────────────────────

export async function getBrains() {
  return apiFetch("/api/brains");
}

// ── Conversations ────────────────────────────────────────────────────────────

export async function getConversations() {
  return apiFetch("/api/conversations");
}

export async function getMessages(conversationId) {
  return apiFetch(`/api/conversations/${conversationId}/messages`);
}

export async function deleteConversation(conversationId) {
  return apiFetch(`/api/conversations/${conversationId}`, { method: "DELETE" });
}

// ── Chat streaming ───────────────────────────────────────────────────────────

// Uses fetch + ReadableStream since the endpoint is POST (EventSource only supports GET).
export async function streamChat({ brainSlug, message, conversationId, onToken, onDone, onError }) {
  const token = await getToken();

  let res;
  try {
    res = await fetch("/api/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${token}`,
      },
      body: JSON.stringify({ brain_slug: brainSlug, message, conversation_id: conversationId || null }),
    });
  } catch (e) {
    onError("Connection failed. Please check your internet and try again.");
    return null;
  }

  if (res.status === 402) {
    const body = await res.json().catch(() => ({}));
    onError(body.detail || "Subscribe to continue chatting.");
    return null;
  }

  if (res.status === 429) {
    const body = await res.json().catch(() => ({}));
    onError(body.detail || "Usage limit reached. Please try again later.");
    return null;
  }

  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    onError(body.detail || "Something went wrong. Please try again.");
    return null;
  }

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let currentConversationId = conversationId;

  const controller = { aborted: false };

  (async () => {
    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done || controller.aborted) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop(); // keep incomplete last line

        for (const line of lines) {
          if (!line.startsWith("data: ")) continue;
          try {
            const data = JSON.parse(line.slice(6));
            if (data.type === "token") {
              if (data.conversation_id) currentConversationId = data.conversation_id;
              onToken(data.text, currentConversationId);
            } else if (data.type === "done") {
              onDone(data.conversation_id || currentConversationId);
            } else if (data.type === "monthly_cost_cap_exceeded") {
              onError(data.message || "You've reached your AI usage limit for this month.");
            } else if (data.type === "error") {
              onError(data.message || "An error occurred during streaming.");
            }
          } catch (_) { /* malformed line, skip */ }
        }
      }
    } catch (e) {
      if (!controller.aborted) onError("Stream interrupted. Please try again.");
    }
  })();

  // Return abort function
  return () => {
    controller.aborted = true;
    reader.cancel();
  };
}

// ── Group chat ───────────────────────────────────────────────────────────────

export async function startGroupChat(brainSlugs, question) {
  return apiFetch("/api/group-chat", {
    method: "POST",
    body: JSON.stringify({ brain_slugs: brainSlugs, question }),
  });
}

export async function getGroupSession(sessionId) {
  return apiFetch(`/api/group-sessions/${sessionId}`);
}

export async function getGroupSessionStatus(sessionId) {
  return apiFetch(`/api/group-chat/${sessionId}/status`);
}

export async function getGroupSessions() {
  return apiFetch("/api/group-sessions");
}

// ── Billing ──────────────────────────────────────────────────────────────────

export async function getBillingStatus() {
  return apiFetch("/api/billing/status");
}

export async function startCheckout() {
  const { url } = await apiFetch("/api/billing/checkout", { method: "POST" });
  window.location.href = url;
}

export async function openBillingPortal() {
  const { url } = await apiFetch("/api/billing/portal", { method: "POST" });
  window.location.href = url;
}
