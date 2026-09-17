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
  user: SessionUser | null;
  ready: boolean;
  configured: boolean;
}

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
