import { act, renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { pageRange, usePageInRange } from "@/hooks/use-paged";

describe("the count under a paged table", () => {
  it("names the window it is showing", () => {
    expect(pageRange(25, 25, 240)).toBe("26–50 of 240");
  });

  it("says none rather than 1–0 of 0", () => {
    expect(pageRange(0, 0, 0)).toBe("none");
  });

  it("does not claim to be showing a row it has not got", () => {
    expect(pageRange(50, 0, 40)).toBe("0 of 40");
  });
});

describe("a page that stopped existing underneath the reader", () => {
  function guard(overrides: Partial<Parameters<typeof usePageInRange>[0]> = {}) {
    const onChange = vi.fn();
    const props = {
      page: 2,
      pageSize: 25,
      total: 40,
      rows: 0,
      settled: true,
      onChange,
      ...overrides,
    };
    renderHook((current: typeof props) => usePageInRange(current), { initialProps: props });
    return onChange;
  }

  it("steps back to the last page that has rows on it", () => {
    expect(guard()).toHaveBeenCalledWith(1);
  });

  it("goes to the first page when everything is gone", () => {
    expect(guard({ total: 0 })).toHaveBeenCalledWith(0);
  });

  it("leaves a page that has rows alone", () => {
    expect(guard({ rows: 25 })).not.toHaveBeenCalled();
  });

  it("leaves the first page alone — there is nowhere to step back to", () => {
    expect(guard({ page: 0 })).not.toHaveBeenCalled();
  });

  it("waits for an answer that belongs to the query being asked", () => {
    expect(guard({ settled: false })).not.toHaveBeenCalled();
    expect(guard({ total: undefined })).not.toHaveBeenCalled();
  });

  it("does not send a reader back to the start on every keystroke", () => {
    const onChange = vi.fn();
    const props = { page: 3, pageSize: 25, total: 400, rows: 25, settled: true, onChange };
    const { rerender } = renderHook((current: typeof props) => usePageInRange(current), {
      initialProps: props,
    });

    act(() => rerender({ ...props, rows: 0, settled: false }));
    expect(onChange).not.toHaveBeenCalled();

    act(() => rerender({ ...props, rows: 0, settled: true, total: 30 }));
    expect(onChange).toHaveBeenCalledWith(1);
  });
});
