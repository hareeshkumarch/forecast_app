"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button } from "@/components/ui/primitives";
import { cn } from "@/lib/utils";

function isStaleBuild(error: unknown): boolean {
  const message = error instanceof Error ? `${error.name} ${error.message}` : String(error);
  return /ChunkLoadError|Loading chunk|Importing a module script failed|dynamically imported module/i.test(
    message,
  );
}

interface Props {
  children: ReactNode;
  label?: string;
  resetKey?: unknown;
  variant?: "page" | "panel";
}

interface State {
  error: unknown;
}

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
