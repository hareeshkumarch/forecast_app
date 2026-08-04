import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { toast, useToastStore } from "@/stores/toast-store";

beforeEach(() => {
  vi.useFakeTimers();
  useToastStore.setState({ toasts: [] });
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
});
