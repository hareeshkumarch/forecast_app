"use client";


import { AlertTriangle, Loader2, type LucideIcon } from "lucide-react";
import type {
  ButtonHTMLAttributes,
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
} from "react";
import { forwardRef } from "react";

import { errorMessage, errorTitle, isRetryable } from "@/lib/errors";
import { cn } from "@/lib/utils";


type ButtonVariant = "primary" | "secondary" | "ghost" | "danger";
type ButtonSize = "sm" | "md";

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    "bg-accent text-white border border-accent hover:bg-accent-hover disabled:bg-accent-disabled disabled:border-accent-disabled",
  secondary:
    "bg-surface text-text-primary border border-border hover:bg-surface-muted hover:border-border-strong",
  ghost: "bg-transparent text-text-secondary border border-transparent hover:bg-surface-muted",
  danger:
    "bg-surface text-negative border border-negative-border hover:bg-negative-soft hover:border-negative",
};

const BUTTON_SIZES: Record<ButtonSize, string> = {
  sm: "h-10 px-3 text-caption gap-1.5 sm:h-7 sm:px-2.5",
  md: "h-11 px-3 text-meta gap-2 sm:h-8",
};

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  loading?: boolean;
  icon?: LucideIcon;
}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(function Button(
  { variant = "secondary", size = "md", loading, icon: Icon, className, children, disabled, ...rest },
  ref,
) {
  return (
    <button
      ref={ref}
      disabled={disabled || loading}
      className={cn(
        "inline-flex items-center justify-center rounded-input font-medium",
        "transition-colors duration-fast disabled:cursor-not-allowed disabled:opacity-70",
        BUTTON_SIZES[size],
        BUTTON_VARIANTS[variant],
        className,
      )}
      {...rest}
    >
      {loading ? (
        <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
      ) : Icon ? (
        <Icon className="h-3.5 w-3.5" aria-hidden />
      ) : null}
      {children}
    </button>
  );
});


export const ICON_BUTTON = cn(
  "inline-flex h-11 w-11 shrink-0 items-center justify-center rounded-input sm:h-8 sm:w-8",
  "border border-transparent text-text-secondary",
  "transition-colors duration-fast hover:border-border hover:bg-surface-muted hover:text-text-primary",
);

export const IconButton = forwardRef<
  HTMLButtonElement,
  ButtonHTMLAttributes<HTMLButtonElement> & { label: string; icon: LucideIcon }
>(function IconButton({ label, icon: Icon, className, ...rest }, ref) {
  return (
    <button
      ref={ref}
      type="button"
      aria-label={label}
      title={label}
      className={cn(ICON_BUTTON, className)}
      {...rest}
    >
      <Icon className="h-4 w-4" aria-hidden />
    </button>
  );
});


export function Card({ className, children }: { className?: string; children: ReactNode }) {
  return <div className={cn("card shadow-card", className)}>{children}</div>;
}


/**
 * Shared chrome for every Radix dropdown/popover surface, so menus in the
 * header, the panels and the rails cannot drift apart.
 */
export const MENU_CONTENT =
  "z-50 min-w-[180px] max-w-[calc(100vw-16px)] rounded-card border border-border bg-surface p-1 shadow-popover";

export const MENU_ITEM = cn(
  "flex cursor-pointer items-center gap-2 rounded-chip px-2 py-1.5 text-meta text-text-primary outline-none",
  "data-[highlighted]:bg-surface-muted",
  "data-[disabled]:cursor-not-allowed data-[disabled]:text-text-muted",
);

export function PanelHeader({
  title,
  subtitle,
  actions,
  className,
}: {
  title: string;
  subtitle?: string;
  actions?: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-start justify-between gap-3 px-4 pb-3 pt-3.5", className)}>
      <div className="min-w-0">
        <h2 className="panel-title truncate">{title}</h2>
        {subtitle ? <p className="mt-0.5 text-caption text-text-muted">{subtitle}</p> : null}
      </div>
      {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
    </div>
  );
}


type BadgeTone = "neutral" | "positive" | "negative" | "warning" | "accent";

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: "bg-surface-muted text-text-secondary border-border",
  positive: "bg-positive-soft text-positive border-positive-border",
  negative: "bg-negative-soft text-negative border-negative-border",
  warning: "bg-warning-soft text-warning border-warning-border",
  accent: "bg-accent-soft text-accent border-accent-border",
};

export function Badge({
  tone = "neutral",
  children,
  className,
}: {
  tone?: BadgeTone;
  children: ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-chip border px-1.5 py-0.5",
        "text-caption font-medium",
        BADGE_TONES[tone],
        className,
      )}
    >
      {children}
    </span>
  );
}


export const Input = forwardRef<HTMLInputElement, InputHTMLAttributes<HTMLInputElement>>(
  function Input({ className, ...rest }, ref) {
    return (
      <input
        ref={ref}
        className={cn(
          "h-11 w-full rounded-input border border-border bg-surface px-2.5 sm:h-8",
          "text-meta text-text-primary placeholder:text-text-muted",
          "transition-colors duration-fast focus:border-accent focus:outline-none",
          "disabled:bg-surface-muted disabled:text-text-muted",
          className,
        )}
        {...rest}
      />
    );
  },
);

export const Select = forwardRef<HTMLSelectElement, SelectHTMLAttributes<HTMLSelectElement>>(
  function Select({ className, children, ...rest }, ref) {
    return (
      <select
        ref={ref}
        className={cn(
          "h-11 w-full rounded-input border border-border bg-surface px-2 sm:h-8",
          "text-meta text-text-primary",
          "transition-colors duration-fast focus:border-accent focus:outline-none",
          "disabled:bg-surface-muted disabled:text-text-muted",
          className,
        )}
        {...rest}
      >
        {children}
      </select>
    );
  },
);

export function Field({
  label,
  hint,
  error,
  required,
  children,
}: {
  label: string;
  hint?: string;
  error?: string;
  required?: boolean;
  children: ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1 flex items-center gap-1 text-caption font-medium text-text-secondary">
        {label}
        {required ? <span className="text-negative">*</span> : null}
      </span>
      {children}
      {error ? (
        <span className="mt-1 block text-caption text-negative">{error}</span>
      ) : hint ? (
        <span className="mt-1 block text-caption text-text-muted">{hint}</span>
      ) : null}
    </label>
  );
}


export function Skeleton({ className }: { className?: string }) {
  return <div className={cn("skeleton", className)} aria-hidden />;
}


export function EmptyState({
  icon: Icon,
  title,
  message,
  action,
  className,
}: {
  icon?: LucideIcon;
  title: string;
  message?: string;
  action?: ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "flex flex-col items-center justify-center gap-2 px-6 py-8 text-center",
        className,
      )}
    >
      {Icon ? (
        <span className="flex h-9 w-9 items-center justify-center rounded-full border border-border bg-surface-muted">
          <Icon className="h-4 w-4 text-text-muted" aria-hidden />
        </span>
      ) : null}
      <p className="text-body font-medium text-text-primary">{title}</p>
      {message ? <p className="max-w-[36ch] text-caption text-text-muted">{message}</p> : null}
      {action ? <div className="mt-1">{action}</div> : null}
    </div>
  );
}

export function ErrorState({
  error,
  title,
  message,
  onRetry,
  className,
}: {
  error?: unknown;
  title?: string;
  message?: string;
  onRetry?: () => void;
  className?: string;
}) {
  const heading = title ?? errorTitle(error, "Couldn't load this panel");
  const detail = message ?? (error === undefined ? undefined : errorMessage(error));
  const canRetry = onRetry && (error === undefined || isRetryable(error));

  return (
    <div
      role="alert"
      className={cn(
        "flex flex-col items-center justify-center gap-2 px-6 py-8 text-center",
        className,
      )}
    >
      <span className="flex h-9 w-9 items-center justify-center rounded-full border border-negative-border bg-negative-soft">
        <AlertTriangle className="h-4 w-4 text-negative" aria-hidden />
      </span>
      <p className="text-body font-medium text-text-primary">{heading}</p>
      {detail ? <p className="max-w-[40ch] text-caption text-text-muted">{detail}</p> : null}
      {canRetry ? (
        <Button size="sm" onClick={onRetry} className="mt-1">
          Retry
        </Button>
      ) : null}
    </div>
  );
}

export function InlineError({
  error,
  message,
  tone = "negative",
  className,
}: {
  error?: unknown;
  message?: string;
  tone?: "negative" | "warning";
  className?: string;
}) {
  const text = message ?? (error === undefined ? null : errorMessage(error));
  if (!text) return null;

  return (
    <p
      role="alert"
      className={cn(
        "flex items-start gap-1.5 rounded-chip px-2 py-1.5 text-caption",
        tone === "negative"
          ? "bg-negative-soft text-negative"
          : "bg-warning-soft text-warning",
        className,
      )}
    >
      <AlertTriangle className="mt-px h-3 w-3 shrink-0" aria-hidden />
      <span className="min-w-0">{text}</span>
    </p>
  );
}
