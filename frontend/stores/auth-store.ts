"use client";

import { useEffect, useState } from "react";

import type { Session, User } from "@supabase/supabase-js";

import { authConfigured, supabase } from "@/lib/supabase";

export interface SessionUser {
  id: string;
  email: string;
  name: string | null;
  picture: string | null;
}

export interface AuthState {
  /** Null until the first check completes — "unknown" and "signed out" differ. */
  user: SessionUser | null;
  ready: boolean;
  /** False when this deployment has no sign-in wired up at all. */
  configured: boolean;
}

/**
 * The signed-in account, or the absence of one.
 *
 * `ready` exists so a page can tell "nobody is signed in" from "we have not
 * looked yet". Without it every guarded route flashes its sign-in prompt on
 * first paint and then replaces it, which reads as being signed out.
 */
export function useAuth(): AuthState {
  const [user, setUser] = useState<SessionUser | null>(null);
  const [ready, setReady] = useState(!authConfigured);

  useEffect(() => {
    const sdk = supabase();
    if (!sdk) return;

    let cancelled = false;

    const adopt = (session: Session | null) => {
      if (cancelled) return;
      const account = session?.user ?? null;
      setUser(
        account
          ? {
              id: account.id,
              email: account.email ?? "",
              name: readMetadata(account, "full_name") ?? readMetadata(account, "name"),
              picture: readMetadata(account, "avatar_url") ?? readMetadata(account, "picture"),
            }
          : null,
      );
      setReady(true);
    };

    void sdk.auth.getSession().then(({ data }) => adopt(data.session));
    const { data: subscription } = sdk.auth.onAuthStateChange((_event, session) =>
      adopt(session),
    );

    return () => {
      cancelled = true;
      subscription.subscription.unsubscribe();
    };
  }, []);

  return { user, ready, configured: authConfigured };
}

function readMetadata(account: User, key: string): string | null {
  const metadata: unknown = account.user_metadata;
  if (metadata && typeof metadata === "object" && key in metadata) {
    const value = (metadata as Record<string, unknown>)[key];
    return value ? String(value) : null;
  }
  return null;
}
