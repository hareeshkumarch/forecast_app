import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, filterParams, getSummary, listConnectors } from "@/lib/api";

function mockFetch(status: number, body: unknown, ok = status < 400) {
  const spy = vi.fn().mockResolvedValue({
    ok,
    status,
    json: async () => body,
  } as Response);
  vi.stubGlobal("fetch", spy);
  return spy;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("filterParams", () => {
  it("maps the store's filter shape onto query parameters", () => {
    expect(
      filterParams({ runId: "abc", start: "2026-01-01", end: "2026-06-01", view: "worst" }),
    ).toEqual({
      run_id: "abc",
      start: "2026-01-01",
      end: "2026-06-01",
      view: "worst",
    });
  });

  it("drops nulls so they never appear in the URL", () => {
    expect(filterParams({ runId: null, start: null, end: null, view: "base" })).toEqual({
      run_id: undefined,
      start: undefined,
      end: undefined,
      view: "base",
    });
  });
});

describe("request handling", () => {
  it("omits empty parameters from the query string", async () => {
    const spy = mockFetch(200, { has_data: false, kpis: [] });

    await getSummary({ runId: null, start: null, end: null, view: "base" });

    const url = spy.mock.calls[0]?.[0] as string;
    expect(url).toContain("view=base");
    expect(url).not.toContain("run_id");
    expect(url).not.toContain("start");
  });

  it("surfaces the backend's error code and message", async () => {
    mockFetch(422, {
      error: { code: "validation_error", message: "'bogus' is not a valid forecast view.", detail: {} },
    });

    await expect(getSummary({ view: "base" } as never)).rejects.toMatchObject({
      status: 422,
      code: "validation_error",
      message: "'bogus' is not a valid forecast view.",
    });
  });

  it("falls back gracefully when the error body is not JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        json: async () => {
          throw new Error("not json");
        },
      } as unknown as Response),
    );

    await expect(listConnectors()).rejects.toMatchObject({
      status: 500,
      code: "http_error",
    });
  });

  it("turns a network failure into a retryable ApiError", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    const error = await listConnectors().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(0);
    expect((error as ApiError).isRetryable).toBe(true);
  });
});

describe("ApiError.isRetryable", () => {
  it("retries transient faults but not client errors", () => {
    expect(new ApiError(0, "network_error", "", {}).isRetryable).toBe(true);
    expect(new ApiError(500, "internal_error", "", {}).isRetryable).toBe(true);
    expect(new ApiError(429, "rate_limited", "", {}).isRetryable).toBe(true);

    expect(new ApiError(404, "not_found", "", {}).isRetryable).toBe(false);
    expect(new ApiError(422, "validation_error", "", {}).isRetryable).toBe(false);
    expect(new ApiError(415, "unsupported_file", "", {}).isRetryable).toBe(false);
  });
});
