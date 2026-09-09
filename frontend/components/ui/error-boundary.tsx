"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

/**
 * A build that moved under an open tab.
 *
 * Every workspace, dialog and drawer in this app arrives through `dynamic()`,
 * so its code is a hashed chunk fetched the first time it is needed. A deploy
 * replaces those hashes. Anybody who had the app open and then opens a dialog
 * for the first time asks for a file that is no longer there, and React throws
 * during render — which, without this, is a blank page.
 *
 * It is worth telling apart from every other error because the fix is
 * different and certain: reload, and it is gone. "Try again" cannot help,
 * because the chunk it would re-request still does not exist.
 */
function isStaleBuild(error: unknown): boolean {
  const message = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  return /ChunkLoadError|Loading chunk|Importing a module script failed|dynamically imported module/i.test(
    message,
  );
}

interface Props {
  children: ReactNode;
  /** Named in the fallback, so "the insights panel" beats "this part of the page". */
  label?: string;
  /** Changing this clears a caught error — a new run id, a different section. */
  resetKey?: unknown;
  variant?: "page" | "panel";
}

interface State {
  error: unknown;
}

/**
 * Stops one broken piece taking the whole page with it.
 *
 * React unmounts the entire tree when a render throws and nothing catches it:
 * an undefined field inside one chart used to leave a white page with no
 * sidebar, no navigation and no way back except the reload the person had no
 * reason to think would help. A boundary around each region turns that into
 * one panel saying so, with the rest of the app still working.
 */
export class ErrorBoundary extends Component<Props, State> {
  override state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { error };
  }

  override componentDidUpdate(previous: Props): void {
    if (this.state.error && previous.resetKey !== this.props.resetKey) {
      this.setState({ error: null });
    }
  }

  override componentDidCatch(error: Error, info: ErrorInfo): void {
    // The console is the only reporter this deployment has. Losing the
    // component stack would leave a bug report saying "a panel broke".
    console.error(`Render failed${this.props.label ? ` in ${this.props.label}` : ""}`, error, info);
  }

  private retry = () => this.setState({ error: null });

  private reload = () => window.location.reload();

  override render(): ReactNode {
    const { error } = this.state;
    if (!error) return this.props.children;

    const stale = isStaleBuild(error);
    const panel = this.props.variant !== "page";

    return (
      <div
        role="alert"
        className={cn(
          "flex flex-col items-center justify-center gap-2 text-center",
          panel ? "px-6 py-10" : "min-h-[60dvh] px-6 py-16",
        )}
      >
        <p className="text-title font-semibold text-text-primary">
          {stale ? "This page is running an older version" : "Something broke here"}
        </p>
        <p className="max-w-[46ch] text-meta leading-relaxed text-text-secondary">
          {stale
            ? "The app was updated while this tab was open, so part of it could not be loaded. Reloading picks up the new version."
            : `${this.props.label ? `The ${this.props.label} ` : "This part of the page "}stopped rendering. The rest of the app is unaffected — nothing you have done was lost.`}
        </p>
        {process.env.NODE_ENV !== "production" && error instanceof Error ? (
          <pre className="scroll-thin mt-1 max-w-full overflow-x-auto rounded-input border border-border bg-surface-muted px-3 py-2 text-left text-caption text-text-muted">
            {error.message}
          </pre>
        ) : null}
        <div className="mt-2 flex flex-wrap items-center justify-center gap-2">
          {stale ? null : (
            <Button size="sm" onClick={this.retry}>
              Try again
            </Button>
          )}
          <Button size="sm" variant={stale ? "primary" : "secondary"} onClick={this.reload}>
            Reload the page
          </Button>
        </div>
      </div>
    );
  }
}
