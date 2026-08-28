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

export async function signInWithGoogle(redirectTo?: string): Promise<void> {
  const sdk = supabase();
  if (!sdk) throw new Error("This deployment has no sign-in configured.");

  await sdk.auth.signInWithOAuth({
    provider: "google",
    options: {
      redirectTo: redirectTo ?? `${window.location.origin}/dashboard`,
    },
  });
}

export async function signOut(): Promise<void> {
  await supabase()?.auth.signOut();
}
