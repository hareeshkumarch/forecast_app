"use client";

import { create } from "zustand";

export type ToastTone = "success" | "error" | "info";

export interface Toast {
  id: string;
  tone: ToastTone;
  title: string;
  description?: string;

  action?: { label: string; onClick: () => void };

  /**
   * How many times the same thing has been said.
   *
   * A retry that fails three times used to be three identical toasts stacked
   * on top of each other, which pushes anything else off the screen and reads
   * as three different problems. One card counting up says more in less room.
   */
  repeats: number;
}

const DURATIONS: Record<ToastTone, number> = {
  success: 4_000,
  info: 5_000,
  error: 8_000,
};

const MAX_VISIBLE = 4;

interface ToastState {
  toasts: Toast[];
  push: (toast: Omit<Toast, "id" | "repeats">) => string;
  dismiss: (id: string) => void;
  clear: () => void;
  /** Stops every countdown — the pointer is over the stack, or the tab is hidden. */
  hold: () => void;
  release: () => void;
}

let counter = 0;

interface Countdown {
  timer: number | null;
  remaining: number;
  startedAt: number;
}

const countdowns = new Map<string, Countdown>();
let held = false;

function clearTimer(id: string): void {
  const countdown = countdowns.get(id);
  if (countdown?.timer !== null && countdown?.timer !== undefined && typeof window !== "undefined") {
    window.clearTimeout(countdown.timer);
  }
}

function forget(id: string): void {
  clearTimer(id);
  countdowns.delete(id);
}

function arm(id: string, remaining: number): void {
  const countdown: Countdown = { timer: null, remaining, startedAt: Date.now() };
  countdowns.set(id, countdown);
  if (held || typeof window === "undefined") return;
  countdown.timer = window.setTimeout(() => useToastStore.getState().dismiss(id), remaining);
}

function sameThing(a: Omit<Toast, "id" | "repeats">, b: Toast): boolean {
  return a.tone === b.tone && a.title === b.title && a.description === b.description;
}

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],

  push: (toast) => {
    const current = get().toasts;

    // Only the newest is compared. A repeat of something further up the stack
    // is a different moment, and moving an old card down to say so would
    // reorder the list under whatever the reader was looking at.
    const newest = current.at(-1);
    if (newest && sameThing(toast, newest)) {
      forget(newest.id);
      arm(newest.id, DURATIONS[toast.tone]);
      set({
        toasts: [
          ...current.slice(0, -1),
          { ...newest, ...toast, id: newest.id, repeats: newest.repeats + 1 },
        ],
      });
      return newest.id;
    }

    counter += 1;
    const id = `toast-${Date.now()}-${counter}`;
    const retained = current.slice(-(MAX_VISIBLE - 1));
    current.slice(0, -(MAX_VISIBLE - 1)).forEach((item) => forget(item.id));

    set({ toasts: [...retained, { ...toast, id, repeats: 1 }] });
    arm(id, DURATIONS[toast.tone]);
    return id;
  },

  dismiss: (id) => {
    forget(id);
    set((state) => ({ toasts: state.toasts.filter((item) => item.id !== id) }));
  },

  clear: () => {
    countdowns.forEach((_countdown, id) => forget(id));
    set({ toasts: [] });
  },

  hold: () => {
    if (held) return;
    held = true;
    countdowns.forEach((countdown, id) => {
      clearTimer(id);
      countdown.remaining = Math.max(0, countdown.remaining - (Date.now() - countdown.startedAt));
      countdown.timer = null;
    });
  },

  release: () => {
    if (!held) return;
    held = false;
    countdowns.forEach((countdown, id) => arm(id, countdown.remaining));
  },
}));

export const toast = {
  success: (title: string, description?: string) =>
    useToastStore.getState().push({ tone: "success", title, description }),
  error: (title: string, description?: string) =>
    useToastStore.getState().push({ tone: "error", title, description }),
  info: (title: string, description?: string) =>
    useToastStore.getState().push({ tone: "info", title, description }),
  action: (
    tone: ToastTone,
    title: string,
    action: { label: string; onClick: () => void },
    description?: string,
  ) => useToastStore.getState().push({ tone, title, description, action }),
};
