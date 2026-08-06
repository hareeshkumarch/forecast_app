"use client";

import { useId, type ComponentType } from "react";

import { cn } from "@/lib/utils";

type Mark = ComponentType<{ className?: string }>;

function Svg({
  className,
  children,
  fill = "currentColor",
}: {
  className?: string;
  children: React.ReactNode;
  fill?: string;
}) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill={fill}
      className={cn("h-4 w-4 shrink-0", className)}
      aria-hidden
      focusable="false"
    >
      {children}
    </svg>
  );
}

function OpenAiMark({ className }: { className?: string }) {
  return (
    <Svg className={cn("text-text-primary", className)}>
      <path d="M22.282 9.821a5.985 5.985 0 0 0-.516-4.911 6.046 6.046 0 0 0-6.51-2.9A6.065 6.065 0 0 0 4.981 4.182a5.985 5.985 0 0 0-3.998 2.9 6.046 6.046 0 0 0 .743 7.097 5.98 5.98 0 0 0 .511 4.91 6.051 6.051 0 0 0 6.515 2.9A5.985 5.985 0 0 0 13.26 24a6.056 6.056 0 0 0 5.772-4.206 5.99 5.99 0 0 0 3.998-2.9 6.056 6.056 0 0 0-.748-7.073Zm-9.022 12.608a4.476 4.476 0 0 1-2.876-1.04l.142-.081 4.778-2.758a.795.795 0 0 0 .393-.681v-6.737l2.02 1.168a.071.071 0 0 1 .038.052v5.583a4.504 4.504 0 0 1-4.495 4.494ZM3.6 18.304a4.471 4.471 0 0 1-.535-3.014l.142.085 4.783 2.758a.771.771 0 0 0 .781 0l5.843-3.368v2.332a.08.08 0 0 1-.034.062L9.74 19.95a4.499 4.499 0 0 1-6.14-1.646ZM2.34 7.896a4.485 4.485 0 0 1 2.366-1.973V11.6a.766.766 0 0 0 .388.677l5.814 3.354-2.02 1.168a.076.076 0 0 1-.071 0l-4.83-2.786A4.504 4.504 0 0 1 2.34 7.872Zm16.597 3.856-5.833-3.388L15.119 7.2a.076.076 0 0 1 .071 0l4.83 2.791a4.494 4.494 0 0 1-.676 8.105v-5.678a.79.79 0 0 0-.407-.666Zm2.01-3.023-.141-.085-4.774-2.782a.776.776 0 0 0-.785 0L9.409 9.23V6.897a.066.066 0 0 1 .028-.061l4.83-2.787a4.499 4.499 0 0 1 6.68 4.66ZM8.307 12.863l-2.02-1.164a.08.08 0 0 1-.038-.057V6.074a4.499 4.499 0 0 1 7.375-3.454l-.142.08L8.704 5.46a.795.795 0 0 0-.393.681Zm1.098-2.365 2.602-1.5 2.607 1.5v3l-2.598 1.5-2.607-1.5Z" />
    </Svg>
  );
}

function ClaudeMark({ className }: { className?: string }) {
  return (
    <Svg className={className} fill="#D97757">
      <g transform="translate(12 12)">
        {Array.from({ length: 10 }, (_, index) => (
          <path
            key={index}
            d="M-1.05 -1.4 L0 -10.4 L1.05 -1.4 Z"
            transform={`rotate(${index * 36})`}
          />
        ))}
        <circle r="2.6" />
      </g>
    </Svg>
  );
}

function GeminiMark({ className }: { className?: string }) {
  const gradient = useId();

  return (
    <Svg className={className} fill={`url(#${gradient})`}>
      <defs>
        <linearGradient id={gradient} x1="0.1" y1="0" x2="0.9" y2="1">
          <stop offset="0%" stopColor="#4285F4" />
          <stop offset="35%" stopColor="#7C6BE8" />
          <stop offset="70%" stopColor="#9B72CB" />
          <stop offset="100%" stopColor="#D96570" />
        </linearGradient>
      </defs>
      <path d="M12 1.2c.35 5.6 5.2 10.45 10.8 10.8-5.6.35-10.45 5.2-10.8 10.8-.35-5.6-5.2-10.45-10.8-10.8C6.8 11.65 11.65 6.8 12 1.2Z" />
    </Svg>
  );
}

function XaiMark({ className }: { className?: string }) {
  return (
    <Svg className={cn("text-text-primary", className)}>
      <path d="M4.2 2.4h4.3l11.3 19.2h-4.3L4.2 2.4Z" />
      <path d="M4 21.6 10.3 13l2.2 3.7-3 4.9H4Z" />
      <path d="M13.6 8.3 11.4 4.6l1.3-2.2h4.5L13.6 8.3Z" />
    </Svg>
  );
}

function OllamaMark({ className }: { className?: string }) {
  return (
    <Svg className={cn("text-text-primary", className)} fill="none">
      <g
        stroke="currentColor"
        strokeWidth="1.7"
        strokeLinecap="round"
        strokeLinejoin="round"
      >

        <path d="M7.8 8.4C7 7.5 6.6 6 6.8 4.6 7 3.3 7.7 2.7 8.4 3c.7.3 1.1 1.5 1.1 2.8 0 .9-.15 1.7-.3 2.2" />
        <path d="M16.2 8.4c.8-.9 1.2-2.4 1-3.8-.2-1.3-.9-1.9-1.6-1.6-.7.3-1.1 1.5-1.1 2.8 0 .9.15 1.7.3 2.2" />

        <path d="M12 7.4c3.2 0 5.6 2.1 5.6 5 0 1.3-.35 2.1-.6 2.9-.2.65-.3 1.1-.3 1.6 0 1.6-.6 3.1-4.7 3.1s-4.7-1.5-4.7-3.1c0-.5-.1-.95-.3-1.6-.25-.8-.6-1.6-.6-2.9 0-2.9 2.4-5 5.6-5Z" />
      </g>
      <circle cx="10" cy="12.4" r="0.95" fill="currentColor" />
      <circle cx="14" cy="12.4" r="0.95" fill="currentColor" />
    </Svg>
  );
}

function monogram(letter: string, background: string, foreground = "#FFFFFF"): Mark {
  function Monogram({ className }: { className?: string }) {
    const shade = useId();
    return (
      <Svg className={className} fill="none">
        <defs>
          <linearGradient id={shade} x1="0" y1="0" x2="0.6" y2="1">
            <stop offset="0%" stopColor={background} />
            <stop offset="100%" stopColor={background} stopOpacity="0.78" />
          </linearGradient>
        </defs>
        <rect width="24" height="24" rx="7" fill={`url(#${shade})`} />
        <text
          x="12"
          y="12.5"
          fill={foreground}
          fontSize={letter.length > 2 ? 8 : letter.length > 1 ? 10 : 13.5}
          fontWeight="700"
          letterSpacing={letter.length > 2 ? "-0.2" : letter.length > 1 ? "-0.5" : "0"}
          fontFamily="var(--font-sans, ui-sans-serif), system-ui, sans-serif"
          textAnchor="middle"
          dominantBaseline="central"
        >
          {letter}
        </text>
      </Svg>
    );
  }

  Monogram.displayName = `Monogram(${letter})`;
  return Monogram;
}

const MARKS: Record<string, Mark> = {
  openai: OpenAiMark,
  anthropic: ClaudeMark,
  gemini: GeminiMark,
  xai: XaiMark,
  groq: monogram("groq", "#F55036"),
  openrouter: monogram("OR", "#6467F2"),
  custom: OllamaMark,
};

export function providerMark(provider: string): Mark {
  return MARKS[provider] ?? MARKS.custom!;
}

export function ProviderLogo({
  provider,
  className,
}: {
  provider: string;
  className?: string;
}) {
  const Mark = providerMark(provider);
  return <Mark className={className} />;
}
