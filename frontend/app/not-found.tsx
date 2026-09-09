import Link from "next/link";

import { Mark } from "@/components/marketing/mark";

export default function NotFound() {
  return (
    <main className="flex min-h-[100dvh] flex-col items-center justify-center gap-3 bg-canvas px-6 text-center">
      <Mark size={34} />
      <h1 className="mt-3 text-heading font-semibold tracking-[-0.02em] text-text-primary">
        There is nothing at this address
      </h1>
      <p className="max-w-[46ch] text-meta leading-relaxed text-text-secondary">
        The link may be old, or the run or dataset it pointed at may have been deleted.
      </p>
      <Link
        href="/dashboard"
        className="mt-3 inline-flex h-9 items-center rounded-input bg-accent px-4 text-meta font-medium text-on-accent transition-colors duration-fast hover:bg-accent-hover"
      >
        Back to the dashboard
      </Link>
    </main>
  );
}
