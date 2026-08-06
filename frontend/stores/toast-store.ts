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

export const useToastStore = create<ToastState>((set, get) => ({
  toasts: [],

  push: (toast) => {
    counter += 1;
    const id = `toast-${counter}`;

    set((state) => ({ toasts: [...state.toasts.slice(-3), { ...toast, id }] }));

    if (typeof window !== "undefined") {
      window.setTimeout(() => get().dismiss(id), DURATIONS[toast.tone]);
    }
    return id;
  },

  dismiss: (id) => set((state) => ({ toasts: state.toasts.filter((item) => item.id !== id) })),
  clear: () => set({ toasts: [] }),
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
