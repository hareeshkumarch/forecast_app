import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useForecastProgress } from "@/hooks/use-forecast-progress";
import type { ForecastProgressEvent } from "@/types/api";

const RUN_ID = "11111111-2222-3333-4444-555555555555";

/** Every EventSource the hook opens, so a test can drive it. */
const opened: FakeEventSource[] = [];

class FakeEventSource {
  onmessage: ((event: { data: string }) => void) | null = null;
  onerror: (() => void) | null = null;
  onopen: (() => void) | null = null;
  closed = false;

  constructor(readonly url: string) {
    opened.push(this);
  }

  close() {
    this.closed = true;
  }

  open() {
    act(() => this.onopen?.());
  }

  emit(event: Partial<ForecastProgressEvent>) {
    const payload: ForecastProgressEvent = {
      run_id: RUN_ID,
      status: "running",
      progress: 0.3,
      stage: "backtesting",
      message: null,
      selected_model: null,
      error: null,
      ...event,
    };
    act(() => this.onmessage?.({ data: JSON.stringify(payload) }));
  }

  fail() {
    act(() => this.onerror?.());
  }
}

const getForecastRun = vi.fn();

vi.mock("@/lib/api", () => ({
  forecastEventsUrl: (id: string) => `http://api.test/api/forecasts/${id}/events`,
  getForecastRun: (id: string) => getForecastRun(id),
}));

beforeEach(() => {
  opened.length = 0;
  getForecastRun.mockReset();
  vi.stubGlobal("EventSource", FakeEventSource);
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllGlobals();
});

describe("following a forecast", () => {
  it("opens nothing until there is a run to watch", () => {
    const { result } = renderHook(() => useForecastProgress(null));

    expect(opened).toHaveLength(0);
    expect(result.current.status).toBe("idle");
  });

  it("reports each stage as it arrives", () => {
    const { result } = renderHook(() => useForecastProgress(RUN_ID));

    expect(opened).toHaveLength(1);
    opened[0]!.open();
    opened[0]!.emit({ status: "running", progress: 0.3, stage: "backtesting" });

    expect(result.current.stage).toBe("backtesting");
    expect(result.current.progress).toBe(0.3);
    expect(result.current.isStreaming).toBe(true);
    expect(result.current.isReconnecting).toBe(false);
  });

  it("announces completion once and closes the stream", () => {
    const onComplete = vi.fn();
    renderHook(() => useForecastProgress(RUN_ID, onComplete));

    opened[0]!.emit({ status: "completed", progress: 1, stage: "complete" });

    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onComplete.mock.calls[0]![0].status).toBe("completed");
    expect(opened[0]!.closed).toBe(true);
  });

  it("reconnects when the stream drops mid-run", async () => {
    const { result } = renderHook(() => useForecastProgress(RUN_ID));

    opened[0]!.open();
    opened[0]!.emit({ status: "running", progress: 0.3, stage: "backtesting" });
    opened[0]!.fail();

    expect(result.current.isReconnecting).toBe(true);
    // The last known stage survives the drop rather than resetting to nothing.
    expect(result.current.stage).toBe("backtesting");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(1_100);
    });

    expect(opened.length).toBeGreaterThan(1);

    opened[1]!.open();
    opened[1]!.emit({ status: "running", progress: 0.75, stage: "fitting" });

    expect(result.current.isReconnecting).toBe(false);
    expect(result.current.progress).toBe(0.75);
  });

  it("falls back to polling when the stream cannot be re-established", async () => {
    getForecastRun.mockResolvedValue({
      id: RUN_ID,
      status: "completed",
      progress: 1,
      stage: "complete",
      selected_model: "theta",
      error_message: null,
    });

    const onComplete = vi.fn();
    renderHook(() => useForecastProgress(RUN_ID, onComplete));

    // Exhaust the reconnection budget.
    for (let attempt = 0; attempt < 6; attempt += 1) {
      const source = opened[opened.length - 1]!;
      source.fail();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(9_000);
      });
    }

    await waitFor(() => expect(getForecastRun).toHaveBeenCalledWith(RUN_ID));
    await waitFor(() => expect(onComplete).toHaveBeenCalledTimes(1));
    expect(onComplete.mock.calls[0]![0].selected_model).toBe("theta");
  });

  it("never calls back twice, even if a late frame arrives", () => {
    const onComplete = vi.fn();
    renderHook(() => useForecastProgress(RUN_ID, onComplete));

    opened[0]!.emit({ status: "completed", stage: "complete", progress: 1 });
    opened[0]!.emit({ status: "completed", stage: "complete", progress: 1 });

    expect(onComplete).toHaveBeenCalledTimes(1);
  });

  it("ignores a truncated frame instead of tearing the stream down", () => {
    const { result } = renderHook(() => useForecastProgress(RUN_ID));

    opened[0]!.emit({ status: "running", progress: 0.5, stage: "fitting" });
    act(() => opened[0]!.onmessage?.({ data: "{not json" }));

    expect(result.current.stage).toBe("fitting");
    expect(opened[0]!.closed).toBe(false);
  });

  it("uses the newest callback rather than the one from the first render", () => {
    const first = vi.fn();
    const second = vi.fn();

    const { rerender } = renderHook(
      ({ callback }) => useForecastProgress(RUN_ID, callback),
      { initialProps: { callback: first } },
    );

    rerender({ callback: second });
    opened[0]!.emit({ status: "completed", stage: "complete", progress: 1 });

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
    expect(opened).toHaveLength(1);
  });

  it("closes the stream when the watcher goes away", () => {
    const { unmount } = renderHook(() => useForecastProgress(RUN_ID));

    unmount();

    expect(opened[0]!.closed).toBe(true);
  });
});
