import { act, renderHook, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  RUN_STAGES,
  STAGE_LABELS,
  stagesFor,
  useElapsed,
  useForecastProgress,
} from "@/hooks/use-forecast-progress";
import type { ForecastProgressEvent } from "@/types/api";

const RUN_ID = "11111111-2222-3333-4444-555555555555";

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

const getForecastProgress = vi.fn();

vi.mock("@/lib/api", () => ({
  forecastEventsUrl: (id: string) => `http://api.test/api/forecasts/${id}/events`,
  getForecastRun: (id: string) => getForecastRun(id),
  getForecastProgress: (id: string) => getForecastProgress(id),
}));

beforeEach(() => {
  opened.length = 0;
  getForecastRun.mockReset();
  getForecastProgress.mockReset();

  getForecastProgress.mockRejectedValue(new Error("nothing to recover"));
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
    getForecastProgress.mockResolvedValue({
      run_id: RUN_ID,
      status: "completed",
      progress: 1,
      stage: "complete",
      message: null,
      selected_model: "theta",
      error: null,
    });

    const onComplete = vi.fn();
    renderHook(() => useForecastProgress(RUN_ID, onComplete));

    for (let attempt = 0; attempt < 6; attempt += 1) {
      const source = opened[opened.length - 1]!;
      source.fail();
      await act(async () => {
        await vi.advanceTimersByTimeAsync(9_000);
      });
    }

    await waitFor(() => expect(getForecastProgress).toHaveBeenCalledWith(RUN_ID));
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

describe("the steps a run is shown as having", () => {
  it("leaves the grain steps out of a run that has no grain", () => {
    expect(stagesFor(false)).toEqual(RUN_STAGES);
    expect(stagesFor(false)).not.toContain("fitting_series");
  });

  it("adds the grain steps after the total is stored", () => {
    const stages = stagesFor(true);

    expect(stages.slice(-2)).toEqual(["fitting_series", "storing_series"]);
    expect(stages.indexOf("fitting_series")).toBeGreaterThan(stages.indexOf("persisting"));
  });

  it("names every step it lists", () => {
    // A step with no label renders as a raw backend identifier.
    for (const stage of stagesFor(true)) {
      expect(STAGE_LABELS[stage], stage).toBeTruthy();
    }
  });

  it("matches the order the backend reports them in", () => {
    // The checklist ticks by index, so a step out of order marks the wrong
    // rows done.
    expect(stagesFor(true)).toEqual([
      "aggregating",
      "backtesting",
      "fitting",
      "building_outputs",
      "persisting",
      "generating_insights",
      "fitting_series",
      "storing_series",
    ]);
  });
});

describe("how long a run has been going", () => {
  it("shows nothing before a run starts", () => {
    const { result } = renderHook(() => useElapsed(null, false));

    expect(result.current).toBeNull();
  });

  it("counts up while the run is going", async () => {
    const started = Date.now();
    const { result } = renderHook(() => useElapsed(started, true));

    expect(result.current).toBe("0:00");

    await act(async () => {
      await vi.advanceTimersByTimeAsync(65_000);
    });

    expect(result.current).toBe("1:05");
  });

  it("stops at the total rather than blanking when the run ends", async () => {
    const started = Date.now();
    const { rerender, result } = renderHook(
      ({ running }) => useElapsed(started, running),
      { initialProps: { running: true } },
    );

    await act(async () => {
      await vi.advanceTimersByTimeAsync(42_000);
    });
    expect(result.current).toBe("0:42");

    rerender({ running: false });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });

    expect(result.current).toBe("0:42");
  });

  it("reports the run's own age, not the age of the panel watching it", async () => {
    // Reopening the modal mid-run remounts the panel; a clock anchored to
    // mount would restart at zero and understate a long run.
    const startedTwoMinutesAgo = Date.now() - 125_000;
    const { result } = renderHook(() => useElapsed(startedTwoMinutesAgo, true));

    expect(result.current).toBe("2:05");
  });
});
