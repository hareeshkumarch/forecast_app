"use client";

import { LogIn } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";

import { Button, Card, Skeleton } from "@/components/ui/primitives";
import { signInWithGoogle } from "@/lib/supabase";
import { useAuth } from "@/stores/auth-store";

/**
 * Stands in front of anything that reads real data.
 *
 * It is a courtesy, not the control: the API refuses an unauthenticated
 * request whether or not this component rendered. What it prevents is the app
 * showing empty panels and error toasts to somebody whose only problem is
 * that they have not signed in yet.
 */
export function SignInGate({ children }: { children: ReactNode }) {
  const { user, ready, configured } = useAuth();

  if (!configured || user) return <>{children}</>;

  if (!ready) {
    return (
      <div className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6">
        <Skeleton className="h-5 w-48" />
        <Skeleton className="mt-3 h-40 w-full" />
      </div>
    );
  }

  return <SignInPrompt />;
}

export function SignInPrompt() {
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);

  async function start() {
    setBusy(true);
    setFailed(null);
    try {
      await signInWithGoogle();
    } catch (error) {
      setBusy(false);
      setFailed(error instanceof Error ? error.message : "Sign-in could not be started.");
    }
  }

  return (
    <div className="mx-auto flex w-full max-w-md flex-col items-center px-4 py-16">
      <Card className="w-full p-6 text-center">
        <h1 className="text-heading font-semibold tracking-[-0.02em] text-text-primary">
          Sign in to continue
        </h1>
        <p className="mt-1.5 text-meta text-text-secondary">
          Your forecasts, datasets and connectors are behind a Google sign-in.
        </p>
        <Button
          variant="primary"
          icon={LogIn}
          loading={busy}
          onClick={() => void start()}
          className="mt-5 w-full justify-center"
        >
          Continue with Google
        </Button>
        {failed ? (
          <p className="mt-3 text-caption text-negative" role="alert">
            {failed}
          </p>
        ) : null}
      </Card>
    </div>
  );
}
