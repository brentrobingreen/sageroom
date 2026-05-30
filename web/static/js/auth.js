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
      s.onerror = () => reject(new Error("Failed to load Supabase SDK"));
      document.head.appendChild(s);
    });
  }

  const { supabaseUrl, supabaseAnonKey } = window.SAGEROOM;
  _supabase = window.supabase.createClient(supabaseUrl, supabaseAnonKey);
  return _supabase;
}

export async function getSupabase() {
  return _initSupabase();
}

export async function getSession() {
  const sb = await getSupabase();
  const { data } = await sb.auth.getSession();
  return data.session;
}

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
  if (error) throw error;
  return data;
}

export async function signIn(email, password) {
  const sb = await getSupabase();
  const { data, error } = await sb.auth.signInWithPassword({ email, password });
  if (error) throw error;
  return data;
}

export async function signOut() {
  const sb = await getSupabase();
  await sb.auth.signOut();
  window.location.href = "/";
}

export async function onAuthStateChange(callback) {
  const sb = await getSupabase();
  sb.auth.onAuthStateChange((_event, session) => callback(session));
}

// Call at the top of every protected page.
// Redirects to landing with ?redirect=<path> if not authenticated.
export async function requireAuth() {
  const session = await getSession();
  if (!session) {
    const redirect = encodeURIComponent(window.location.pathname + window.location.search);
    window.location.href = `/?auth=signin&redirect=${redirect}`;
    throw new Error("Redirecting to login");
  }
  return session;
}
