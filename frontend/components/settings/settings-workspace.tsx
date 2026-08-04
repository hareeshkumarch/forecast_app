"use client";

import { SettingsPanel } from "@/components/dashboard/settings-modal";

export function SettingsWorkspace() {
  return (
    <main id="main-content" className="scroll-thin min-w-0 flex-1 overflow-y-auto bg-canvas px-4 py-4 sm:px-6 sm:py-5">
      <div>
        <h1 className="text-heading font-semibold tracking-[-0.015em] text-text-primary">Settings</h1>
        <p className="mt-0.5 text-meta text-text-secondary">
          Control appearance, API connectivity, LLM providers, and fallback pricing.
        </p>
      </div>
      <SettingsPanel className="mt-4" />
    </main>
  );
}
