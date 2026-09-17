import { createClient, type SupabaseClient } from "@supabase/supabase-js";

const URL = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const ANON_KEY = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

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
  const { data } = await sdk.auth.getSession();
  return data.session?.access_token ?? null;
}

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
