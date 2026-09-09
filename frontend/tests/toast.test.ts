import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toast, useToastStore } from "@/stores/toast-store";

beforeEach(() => {
  vi.useFakeTimers();
  useToastStore.getState().release();
  useToastStore.getState().clear();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("toasts", () => {
  it("queues a toast and dismisses it after its lifetime", () => {
    toast.success("Saved");
    expect(useToastStore.getState().toasts).toHaveLength(1);

    vi.advanceTimersByTime(4_000);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("keeps errors on screen longer than confirmations", () => {
    toast.error("Broke");

    vi.advanceTimersByTime(4_000);
    expect(useToastStore.getState().toasts).toHaveLength(1);

    vi.advanceTimersByTime(4_000);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("caps the stack so a burst cannot cover the page", () => {
    for (let index = 0; index < 8; index += 1) toast.info(`Message ${index}`);

    const { toasts } = useToastStore.getState();
    expect(toasts.length).toBeLessThanOrEqual(4);
    expect(toasts.at(-1)?.title).toBe("Message 7");
  });

  it("dismisses on request and carries an optional action", () => {
    const onClick = vi.fn();
    toast.action("info", "Run finished", { label: "View", onClick });

    const [item] = useToastStore.getState().toasts;
    expect(item?.action?.label).toBe("View");

    item?.action?.onClick();
    expect(onClick).toHaveBeenCalledOnce();

    useToastStore.getState().dismiss(item!.id);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("counts a repeat rather than stacking the same message again", () => {
    toast.error("Upload failed", "The connection dropped.");
    toast.error("Upload failed", "The connection dropped.");
    toast.error("Upload failed", "The connection dropped.");

    const { toasts } = useToastStore.getState();
    expect(toasts).toHaveLength(1);
    expect(toasts[0]?.repeats).toBe(3);
  });

  it("gives a repeat its full lifetime back", () => {
    toast.error("Upload failed");
    vi.advanceTimersByTime(7_000);

    toast.error("Upload failed");
    vi.advanceTimersByTime(7_000);
    expect(useToastStore.getState().toasts).toHaveLength(1);

    vi.advanceTimersByTime(1_500);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("treats a different message as a different toast", () => {
    toast.error("Upload failed");
    toast.error("Import failed");

    expect(useToastStore.getState().toasts).toHaveLength(2);
  });

  it("stops the countdown while the stack is held, and resumes where it left off", () => {
    toast.success("Saved");

    vi.advanceTimersByTime(3_000);
    useToastStore.getState().hold();

    vi.advanceTimersByTime(60_000);
    expect(useToastStore.getState().toasts).toHaveLength(1);

    useToastStore.getState().release();
    vi.advanceTimersByTime(900);
    expect(useToastStore.getState().toasts).toHaveLength(1);

    vi.advanceTimersByTime(200);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });

  it("does not start a countdown for a toast raised while held", () => {
    useToastStore.getState().hold();
    toast.info("Arrived while the tab was hidden");

    vi.advanceTimersByTime(60_000);
    expect(useToastStore.getState().toasts).toHaveLength(1);

    useToastStore.getState().release();
    vi.advanceTimersByTime(5_000);
    expect(useToastStore.getState().toasts).toHaveLength(0);
  });
});
