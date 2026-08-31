import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, deleteConnector, filterParams, getSummary, listConnectors } from "@/lib/api";
import { errorMessage, errorTitle, isRetryable } from "@/lib/errors";

function mockFetch(status: number, body: unknown, ok = status < 400, headers: HeadersInit = {}) {
  const spy = vi.fn().mockResolvedValue({
    ok,
    status,
    headers: new Headers(headers),
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

  it("reads with no-cache so the browser can revalidate rather than refetch", async () => {
    // Not "no-store". The dashboard reads carry an ETag over a version derived
    // from the run itself, and the whole saving is the 304: the server skips
    // its aggregate queries entirely. "no-store" would mean the browser keeps
    // no copy and sends no `If-None-Match`, so that path would never be taken
    // and the validators would be decoration.
    const spy = mockFetch(200, { has_data: false, kpis: [] });

    await getSummary({ view: "base" } as never);

    expect(spy.mock.calls[0]?.[1]).toMatchObject({ cache: "no-cache" });
  });

  it("writes with no-store, because there is nothing to revalidate", async () => {
    const spy = mockFetch(204, null);

    await deleteConnector("abc");

    expect(spy.mock.calls[0]?.[1]).toMatchObject({ cache: "no-store" });
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
        headers: new Headers(),
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

  it("keeps the request id so a server error can be traced", async () => {
    mockFetch(
      500,
      {
        error: {
          code: "internal_error",
          message: "Something went wrong on our side.",
          detail: {},
          request_id: "a1b2c3d4e5f6",
        },
      },
      false,
    );

    const error = (await listConnectors().catch((e: unknown) => e)) as ApiError;

    expect(error.requestId).toBe("a1b2c3d4e5f6");
    expect(errorMessage(error)).toContain("a1b2c3d4e5f6");
  });

  it("falls back to the response header when the body carries no request id", async () => {
    mockFetch(500, { error: { code: "internal_error", message: "Boom.", detail: {} } }, false, {
      "X-Request-ID": "header-id-9",
    });

    const error = (await listConnectors().catch((e: unknown) => e)) as ApiError;

    expect(error.requestId).toBe("header-id-9");
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

describe("user-facing error copy", () => {
  it("titles each failure by what the user can do about it", () => {
    expect(errorTitle(new ApiError(0, "network_error", "", {}))).toBe("Can't reach the server");
    expect(errorTitle(new ApiError(422, "validation_error", "", {}))).toBe(
      "Check the highlighted fields",
    );
    expect(errorTitle(new ApiError(503, "internal_error", "", {}))).toBe(
      "The server had a problem",
    );
    expect(errorTitle(new Error("raw"))).toBe("Something went wrong");
    expect(errorTitle(undefined, "Couldn't load this panel")).toBe("Couldn't load this panel");
  });

  it("only attaches a reference to server-side failures", () => {
    expect(errorMessage(new ApiError(500, "internal_error", "Boom.", {}, "abc123"))).toBe(
      "Boom. (reference abc123)",
    );
    expect(errorMessage(new ApiError(422, "validation_error", "Fix it.", {}, "abc123"))).toBe(
      "Fix it.",
    );
  });

  it("falls back for values that are not errors at all", () => {
    expect(errorMessage(null)).toBe("Try again in a moment.");
    expect(errorMessage(new Error("plain failure"))).toBe("plain failure");
    expect(isRetryable(new ApiError(404, "not_found", "", {}))).toBe(false);
    expect(isRetryable(new Error("unknown"))).toBe(true);
  });
});
