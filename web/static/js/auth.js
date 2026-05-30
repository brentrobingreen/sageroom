/* Sageroom — Auth module
   Depends on: /config.js (sets window.SAGEROOM), Supabase JS from CDN
*/

const SUPABASE_CDN = "https://cdn.jsdelivr.net/npm/@supabase/supabase-js@2/dist/umd/supabase.js";

let _supabase = null;

async function _initSupabase() {
  if (_supabase) return _supabase;

  if (!window.supabase) {
    await new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = SUPABASE_CDN;
      s.onload = resolve;
      s.onerror = () => reject(new Error("Failed to load Supabase SDK. Check your internet connection."));
      document.head.appendChild(s);
    });
  }

  const { supabaseUrl, supabaseAnonKey } = window.SAGEROOM;
  if (!supabaseUrl || !supabaseAnonKey) {
    throw new Error("App configuration not loaded. Please refresh the page.");
  }
  _supabase = window.supabase.createClient(supabaseUrl, supabaseAnonKey);
  return _supabase;
}

// Map Supabase's terse error messages to human-readable ones.
function _friendlyError(error) {
  const msg = (error?.message || "").toLowerCase();
  if (msg.includes("invalid login credentials") || msg.includes("invalid email or password")) {
    return "Incorrect email or password. Please try again.";
  }
  if (msg.includes("email not confirmed")) {
    return "Please confirm your email address before signing in. Check your inbox for a confirmation link.";
  }
  if (msg.includes("user already registered")) {
    return "An account with this email already exists. Try signing in instead.";
  }
  if (msg.includes("password should be at least")) {
    return "Password must be at least 6 characters.";
  }
  if (msg.includes("unable to validate email address")) {
    return "Please enter a valid email address.";
  }
  if (msg.includes("email rate limit exceeded") || msg.includes("too many requests")) {
    return "Too many attempts. Please wait a few minutes and try again.";
  }
  if (msg.includes("network") || msg.includes("fetch")) {
    return "Network error. Please check your connection and try again.";
  }
  return error?.message || "Something went wrong. Please try again.";
}

export async function getSupabase() {
  return _initSupabase();
}

export async function getSession() {
  const sb = await getSupabase();
  const { data } = await sb.auth.getSession();
  return data.session;
}

// Always returns a fresh token — Supabase auto-refreshes before expiry.
export async function getToken() {
  const session = await getSession();
  return session?.access_token ?? null;
}

export async function getUser() {
  const session = await getSession();
  return session?.user ?? null;
}

export async function signUp(email, password) {
  const sb = await getSupabase();
  const { data, error } = await sb.auth.signUp({ email, password });
  if (error) throw new Error(_friendlyError(error));

  // If Supabase email confirmation is enabled, identities array is present but
  // user.confirmed_at is null. Detect this and signal back to the caller.
  const needsConfirmation = data.user && !data.user.confirmed_at && data.user.identities?.length > 0;
  return { ...data, needsConfirmation };
}

export async function signIn(email, password) {
  const sb = await getSupabase();
  const { data, error } = await sb.auth.signInWithPassword({ email, password });
  if (error) throw new Error(_friendlyError(error));
  return data;
}

export async function signOut() {
  const sb = await getSupabase();
  await sb.auth.signOut();
  window.location.href = "/";
}

// Call at the top of every protected page.
// Redirects to landing with ?auth=signin&redirect=<path> if not authenticated.
export async function requireAuth() {
  const session = await getSession();
  if (!session) {
    const redirect = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/?auth=signin&redirect=${redirect}`;
    throw new Error("Redirecting to login");
  }
  return session;
}

// Wire up on every protected page after requireAuth().
// Redirects to login if the session is signed out or expires mid-session.
export async function setupSessionMonitor() {
  const sb = await getSupabase();
  sb.auth.onAuthStateChange((event) => {
    if (event === "SIGNED_OUT") {
      const redirect = encodeURIComponent(window.location.pathname);
      window.location.href = `/?auth=signin&redirect=${redirect}`;
    }
  });
}
