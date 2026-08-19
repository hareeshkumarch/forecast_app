"use client";

import { Clock, LogIn, ShieldX } from "lucide-react";
import type { ReactNode } from "react";
import { useState } from "react";

import { Button, Card, Skeleton } from "@/components/ui/primitives";
import { useCurrentUser } from "@/hooks/use-dashboard";
import { signInWithGoogle, signOut } from "@/lib/supabase";
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


/**
 * Signed in, and waiting on somebody.
 *
 * Kept apart from the sign-in prompt because showing "sign in" to a person who
 * has just signed in reads as a failure they can fix by trying again, which
 * they cannot. The request has been made; what is left is to wait.
 */
export function AwaitingApproval({ email }: { email: string | null }) {
  return (
    <div className="mx-auto flex w-full max-w-md flex-col items-center px-4 py-16">
      <Card className="w-full p-6 text-center">
        <Clock className="mx-auto h-6 w-6 text-text-muted" aria-hidden />
        <h1 className="mt-3 text-heading font-semibold tracking-[-0.02em] text-text-primary">
          Waiting for approval
        </h1>
        <p className="mt-1.5 text-meta text-text-secondary">
          {email ? <span className="text-text-primary">{email}</span> : "This account"} has been
          sent to an administrator. You will be able to sign in as soon as it is approved.
        </p>
        <Button
          variant="secondary"
          onClick={() => void signOut().then(() => window.location.assign("/"))}
          className="mt-5 w-full justify-center"
        >
          Sign out
        </Button>
      </Card>
    </div>
  );
}

export function AccessRefused() {
  return (
    <div className="mx-auto flex w-full max-w-md flex-col items-center px-4 py-16">
      <Card className="w-full p-6 text-center">
        <ShieldX className="mx-auto h-6 w-6 text-negative" aria-hidden />
        <h1 className="mt-3 text-heading font-semibold tracking-[-0.02em] text-text-primary">
          No access to this workspace
        </h1>
        <p className="mt-1.5 text-meta text-text-secondary">
          This account was not approved. If that is unexpected, ask whoever runs this
          deployment.
        </p>
        <Button
          variant="secondary"
          onClick={() => void signOut().then(() => window.location.assign("/"))}
          className="mt-5 w-full justify-center"
        >
          Sign out
        </Button>
      </Card>
    </div>
  );
}

/**
 * The whole decision: signed out, waiting, refused, or through.
 *
 * `/auth/me` is the authority rather than the token, because approval is a
 * fact about the account that Google knows nothing about.
 */
export function AccessGate({ children }: { children: ReactNode }) {
  const { user, ready, configured } = useAuth();
  const { data, isPending } = useCurrentUser();

  if (!configured) return <>{children}</>;
  if (!ready) return <GateSkeleton />;
  if (!user) return <SignInPrompt />;
  if (isPending) return <GateSkeleton />;

  if (data?.status === "pending") return <AwaitingApproval email={data.email} />;
  if (data?.status === "rejected") return <AccessRefused />;
  return <>{children}</>;
}

function GateSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6">
      <Skeleton className="h-5 w-48" />
      <Skeleton className="mt-3 h-40 w-full" />
    </div>
  );
}
