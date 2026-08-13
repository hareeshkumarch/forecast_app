"use client";

import { create } from "zustand";

export type ConfirmTone = "danger" | "default";

export interface ConfirmRequest {
  title: string;
  message: string;
  confirmLabel?: string;
  cancelLabel?: string;
  tone?: ConfirmTone;
}

interface ConfirmState {
  request: (ConfirmRequest & { id: number }) | null;
  ask: (request: ConfirmRequest) => Promise<boolean>;
  resolve: (answer: boolean) => void;
}

let counter = 0;
let pending: ((answer: boolean) => void) | null = null;

export const useConfirmStore = create<ConfirmState>((set, get) => ({
  request: null,

  ask: (request) => {
    // A second ask while one is open answers the first with "no", so the
    // caller waiting on it always gets a decision back.
    get().resolve(false);
    counter += 1;
    const decision = new Promise<boolean>((settle) => {
      pending = settle;
    });
    set({ request: { ...request, id: counter } });
    return decision;
  },

  resolve: (answer) => {
    const settle = pending;
    pending = null;
    set({ request: null });
    settle?.(answer);
  },
}));

export const confirm = (request: ConfirmRequest) => useConfirmStore.getState().ask(request);
