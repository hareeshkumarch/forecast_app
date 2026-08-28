"use client";

import { Clock, ShieldX } from "lucide-react";
import type { ReactNode } from "react";
import { useEffect, useState } from "react";

import { Mark } from "@/components/marketing/mark";
import { Button, Skeleton } from "@/components/ui/primitives";
import { signInWithGoogle, signOut } from "@/lib/supabase";
import { cn } from "@/lib/utils";
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

/**
 * The Google mark, drawn rather than fetched.
 *
 * Google's brand guidelines ask for their own glyph on a sign-in button, and
 * people look for it — a generic arrow makes the button read as "next" rather
 * than "this signs you in with Google". Inline, because a remote asset here
 * would be a blocking request on the one screen that must always render.
 */
function GoogleMark({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden className="shrink-0">
      <path
        fill="#4285F4"
        d="M45.12 24.5c0-1.56-.14-3.06-.4-4.5H24v8.51h11.84c-.51 2.75-2.06 5.08-4.39 6.64v5.52h7.11c4.16-3.83 6.56-9.47 6.56-16.17z"
      />
      <path
        fill="#34A853"
        d="M24 46c5.94 0 10.92-1.97 14.56-5.33l-7.11-5.52c-1.97 1.32-4.49 2.1-7.45 2.1-5.73 0-10.58-3.87-12.31-9.07H4.34v5.7C7.96 41.07 15.4 46 24 46z"
      />
      <path
        fill="#FBBC05"
        d="M11.69 28.18c-.44-1.32-.69-2.73-.69-4.18s.25-2.86.69-4.18v-5.7H4.34C2.85 17.09 2 20.45 2 24s.85 6.91 2.34 9.88l7.35-5.7z"
      />
      <path
        fill="#EA4335"
        d="M24 10.75c3.23 0 6.13 1.11 8.41 3.29l6.31-6.31C34.91 4.18 29.93 2 24 2 15.4 2 7.96 6.93 4.34 14.12l7.35 5.7c1.73-5.2 6.58-9.07 12.31-9.07z"
      />
    </svg>
  );
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
    <AuthScreen>
      <div className="flex items-center gap-2.5">
        <Mark size={30} />
        <span className="text-heading font-semibold tracking-[-0.02em] text-text-primary">
          Forecast Hub
        </span>
      </div>

      <h1 className="mt-7 text-[1.55rem] font-semibold leading-[1.2] tracking-[-0.025em] text-text-primary">
        Plan against a forecast
        <br />
        you can question.
      </h1>
      <p className="mt-2.5 text-meta leading-relaxed text-text-secondary">
        Sign in to reach your datasets, runs and connectors.
      </p>

      <button
        type="button"
        onClick={() => void start()}
        disabled={busy}
        className={cn(
          "mt-7 inline-flex h-11 w-full items-center justify-center gap-3 rounded-input",
          "border border-border-strong bg-surface text-meta font-medium text-text-primary",
          "transition-colors duration-fast hover:border-accent-border hover:bg-surface-muted",
          "focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2",
          "focus-visible:outline-accent disabled:pointer-events-none disabled:opacity-60",
        )}
      >
        <GoogleMark />
        {busy ? "Opening Google…" : "Continue with Google"}
      </button>

      {failed ? (
        <p className="mt-3 text-caption text-negative" role="alert">
          {failed}
        </p>
      ) : null}

      <p className="mt-6 border-t border-border pt-4 text-caption leading-relaxed text-text-muted">
        New accounts are reviewed before they can see anything. You will be told when yours is
        approved.
      </p>
    </AuthScreen>
  );
}

/**
 * The frame every one of these screens sits in.
 *
 * One column, held above centre rather than in it: a card pinned to the exact
 * middle of a tall window reads as floating, and the eye expects the first
 * thing on a page to sit a little high.
 */
function AuthScreen({ children }: { children: ReactNode }) {
  return (
    <div className="relative flex min-h-[100dvh] w-full items-start justify-center overflow-hidden bg-canvas px-5 pt-[14vh]">
      {/* A single soft wash behind the card. Enough that the screen is not a
          blank sheet, faint enough that nothing competes with the button. */}
      <div
        aria-hidden
        className="pointer-events-none absolute left-1/2 top-0 h-[420px] w-[820px] -translate-x-1/2 -translate-y-1/3 rounded-full opacity-[0.55] blur-3xl"
        style={{
          background:
            "radial-gradient(closest-side, var(--accent-soft), transparent 72%)",
        }}
      />
      <div className="relative w-full max-w-[26rem]">
        <div className="rounded-card border border-border bg-surface p-7 shadow-[var(--shadow-panel,0_1px_2px_rgba(0,0,0,0.04))]">
          {children}
        </div>
      </div>
    </div>
  );
}

/**
 * Signed in, and waiting on somebody.
 *
 * Kept apart from the sign-in prompt because showing "sign in" to a person who
 * has just signed in reads as a failure they can retry, which it is not. The
 * request has been made; what is left is to wait.
 */
export function AwaitingApproval({ email }: { email: string | null }) {
  return (
    <AuthScreen>
      <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-warning-soft">
        <Clock className="h-4 w-4 text-warning" aria-hidden />
      </span>
      <h1 className="mt-5 text-[1.35rem] font-semibold leading-tight tracking-[-0.02em] text-text-primary">
        Waiting for approval
      </h1>
      <p className="mt-2 text-meta leading-relaxed text-text-secondary">
        {email ? (
          <>
            <span className="font-medium text-text-primary">{email}</span> has been sent to an
            administrator.
          </>
        ) : (
          "Your account has been sent to an administrator."
        )}{" "}
        This page lets you in by itself the moment it is approved — you do not need to reload it,
        and you do not need to keep it open.
      </p>
      <SecondaryAction label="Sign out" />
    </AuthScreen>
  );
}

export function AccessRefused() {
  return (
    <AuthScreen>
      <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-negative-soft">
        <ShieldX className="h-4 w-4 text-negative" aria-hidden />
      </span>
      <h1 className="mt-5 text-[1.35rem] font-semibold leading-tight tracking-[-0.02em] text-text-primary">
        No access to this workspace
      </h1>
      <p className="mt-2 text-meta leading-relaxed text-text-secondary">
        This account was not approved. If that is unexpected, ask whoever runs this deployment —
        signing in again will not change it.
      </p>
      <SecondaryAction label="Sign out" />
    </AuthScreen>
  );
}

function SecondaryAction({ label }: { label: string }) {
  return (
    <Button
      variant="secondary"
      onClick={() => void signOut().then(() => window.location.assign("/signin"))}
      className="mt-6 w-full justify-center"
    >
      {label}
    </Button>
  );
}

function GateSkeleton() {
  return (
    <div className="mx-auto w-full max-w-[1400px] px-4 py-6 sm:px-6">
      <Skeleton className="h-5 w-48" />
      <Skeleton className="mt-3 h-40 w-full" />
    </div>
  );
}


/**
 * Says out loud that this build cannot sign anybody in.
 *
 * The keys are compiled into the bundle, so their absence is decided at build
 * time and nothing at runtime can recover from it. Naming the two variables is
 * the whole message: whoever sees this needs to set them and rebuild.
 */
export function NotConfiguredBanner() {
  return (
    <div
      role="status"
      className="border-b border-warning-border bg-warning-soft px-4 py-2 text-caption text-text-primary"
    >
      <strong className="font-medium">Sign-in is not configured in this build.</strong>{" "}
      <span className="text-text-secondary">
        NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY were missing when it was
        compiled. Set them and redeploy without the build cache — they are baked in at build
        time, so setting them alone changes nothing.
      </span>
    </div>
  );
}


/**
 * The sign-in page at its own address.
 *
 * /dashboard rendering a sign-in form works, but it is the wrong thing to
 * link somebody to and the wrong thing to land on after signing out — the
 * name of the page should say what is on it. Somebody already signed in is
 * sent along rather than shown a button they do not need.
 */
export function SignInScreen() {
  const { user, ready, configured } = useAuth();

  useEffect(() => {
    if (!configured || (ready && user)) window.location.replace("/dashboard");
  }, [configured, ready, user]);

  if (!ready || user) return <GateSkeleton />;
  return <SignInPrompt />;
}
