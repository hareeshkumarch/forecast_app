"use client";

import { create } from "zustand";

export type ToastTone = "success" | "error" | "info";

export interface Toast {
  id: string;
  tone: ToastTone;
  title: string;
  description?: string;

  action?: { label: string; onClick: () => void };
}

const DURATIONS: Record<ToastTone, number> = {
  success: 4_000,
  info: 5_000,
  error: 8_000,
};

interface ToastState {
  toasts: Toast[];
  push: (toast: Omit<Toast, "id">) => string;
  dismiss: (id: string) => void;
  clear: () => void;
}

let counter = 0;
const timers = new Map<string, number>();

function clearTimer(id: string): void {
  const timer = timers.get(id);
  if (timer !== undefined && typeof window !== "undefined") window.clearTimeout(timer);
  timers.delete(id);
}

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],

  push: (toast) => {
    counter += 1;
    const id = `toast-${Date.now()}-${counter}`;
    const current = get().toasts;
    const retained = current.slice(-3);
    current.slice(0, -3).forEach((item) => clearTimer(item.id));

    set({ toasts: [...retained, { ...toast, id }] });

    if (typeof window !== "undefined") {
      timers.set(id, window.setTimeout(() => get().dismiss(id), DURATIONS[toast.tone]));
    }
    return id;
  },

  dismiss: (id) => {
    clearTimer(id);
    set((state) => ({ toasts: state.toasts.filter((item) => item.id !== id) }));
  },
  clear: () => {
    timers.forEach((_timer, id) => clearTimer(id));
    set({ toasts: [] });
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
