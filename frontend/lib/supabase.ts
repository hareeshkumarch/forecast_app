import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

/**
 * Whether this build was given a Supabase project to sign in against.
 *
 * Checked rather than assumed, because the deployment that has the keys and
 * the one that does not are both real: local development runs without them,
 * and the backend answers `authenticated: false` in that case rather than
 * refusing. A missing key should leave the app open, not broken.
 */
export const authConfigured = Boolean(URL && ANON_KEY);

let client: SupabaseClient | null = null;

export function supabase(): SupabaseClient | null {
  if (!authConfigured) return null;
  client ??= createClient(URL, ANON_KEY, {
    auth: {
      persistSession: true,
      autoRefreshToken: true,
      detectSessionInUrl: true,
    },
  });
  return client;
}

export async function accessToken(): Promise<string | null> {
  const sdk = supabase();
  if (!sdk) return null;
  // getSession refreshes an expired token rather than handing one back that
  // the API is about to reject.
  const { data } = await sdk.auth.getSession();
  return data.session?.access_token ?? null;
}

/**
 * A token minted now, whatever is cached.
 *
 * `getSession` hands back a token it believes is still good, and it can be
 * wrong in one narrow window: the token expired between the client's clock
 * saying it had a minute left and the API checking it. The symptom is a 401
 * on a page that was working a second ago, and the fix is a refresh rather
 * than sending the same dead token again.
 */
export async function refreshedAccessToken(): Promise<string | null> {
  const sdk = supabase();
  if (!sdk) return null;
  const { data, error } = await sdk.auth.refreshSession();
  if (error) return null;
  return data.session?.access_token ?? null;
}

export async function signInWithGoogle(redirectTo?: string): Promise<void> {
  const sdk = supabase();
  if (!sdk) throw new Error("This deployment has no sign-in configured.");

  // signInWithOAuth reports a failure in its result rather than by throwing,
  // so without this a provider that refuses leaves the button saying "Opening
  // Google…" for as long as the person is willing to wait for a redirect that
  // is never coming.
  const { error } = await sdk.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: redirectTo ?? `${window.location.origin}/dashboard`,
    },
  });
  if (error) throw new Error(error.message || "Sign-in could not be started.");
}

export async function signOut(): Promise<void> {
  await supabase()?.auth.signOut();
}
