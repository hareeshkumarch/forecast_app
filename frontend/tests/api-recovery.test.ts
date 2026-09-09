import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const refreshedAccessToken = vi.fn();

vi.mock("@/lib/supabase", () => ({
  authConfigured: true,
  accessToken: () => Promise.resolve("stale-token"),
  refreshedAccessToken: () => refreshedAccessToken(),
}));

import { listConnectors } from "@/lib/api";
import type { ApiError } from "@/lib/api";

function answer(status: number, body: unknown, headers: HeadersInit = {}) {
  return {
    ok: status < 400,
    status,
    headers: new Headers(headers),
    json: async () => body,
  } as Response;
}

const denied = {
  error: { code: "unauthenticated", message: "This session has expired.", detail: {} },
};

beforeEach(() => {
  refreshedAccessToken.mockReset();
  vi.stubGlobal("navigator", { onLine: true });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("a session that expired between being attached and being checked", () => {
  it("mints a token and sends the request again", async () => {
    refreshedAccessToken.mockResolvedValue("fresh-token");
    const fetchSpy = vi
      .fn()
      .mockResolvedValueOnce(answer(401, denied))
      .mockResolvedValueOnce(answer(200, []));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(listConnectors()).resolves.toEqual([]);

    expect(fetchSpy).toHaveBeenCalledTimes(2);
    const retried = fetchSpy.mock.calls[1]?.[1] as RequestInit;
    expect(new Headers(retried.headers).get("Authorization")).toBe("Bearer fresh-token");
  });

  it("gives up after one retry rather than looping on a dead session", async () => {
    refreshedAccessToken.mockResolvedValue("fresh-token");
    const fetchSpy = vi.fn().mockResolvedValue(answer(401, denied));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(listConnectors()).rejects.toMatchObject({ status: 401 });
    expect(fetchSpy).toHaveBeenCalledTimes(2);
  });

  it("does not resend anything when the refresh itself fails", async () => {
    refreshedAccessToken.mockResolvedValue(null);
    const fetchSpy = vi.fn().mockResolvedValue(answer(401, denied));
    vi.stubGlobal("fetch", fetchSpy);

    await expect(listConnectors()).rejects.toMatchObject({ status: 401 });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
  });

  it("leaves a 403 alone — that is a decision, not a stale token", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(
      answer(403, {
        error: { code: "forbidden", message: "Not for you.", detail: { status: "rejected" } },
      }),
    );
    vi.stubGlobal("fetch", fetchSpy);

    await expect(listConnectors()).rejects.toMatchObject({ status: 403 });
    expect(fetchSpy).toHaveBeenCalledTimes(1);
    expect(refreshedAccessToken).not.toHaveBeenCalled();
  });
});

describe("what the server said to wait", () => {
  it("reads Retry-After in seconds", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        answer(429, { error: { code: "rate_limited", message: "Slow down.", detail: {} } }, {
          "Retry-After": "30",
        }),
      ),
    );

    await expect(listConnectors()).rejects.toMatchObject({ retryAfterMs: 30_000 });
  });

  it("reads Retry-After as an HTTP date", async () => {
    const when = new Date(Date.now() + 45_000).toUTCString();
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        answer(503, { error: { code: "overloaded", message: "Full.", detail: {} } }, {
          "Retry-After": when,
        }),
      ),
    );

    const failure = (await listConnectors().catch((error) => error)) as ApiError;
    expect(failure.retryAfterMs).toBeGreaterThan(40_000);
    expect(failure.retryAfterMs).toBeLessThanOrEqual(46_000);
  });

  it("falls back to the delay named in the body", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        answer(429, {
          error: {
            code: "too_many_streams",
            message: "Too many.",
            detail: { retry_after_seconds: 15 },
          },
        }),
      ),
    );

    await expect(listConnectors()).rejects.toMatchObject({ retryAfterMs: 15_000 });
  });

  it("says nothing rather than guessing when the server did not", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        answer(500, { error: { code: "internal_error", message: "Broke.", detail: {} } }),
      ),
    );

    await expect(listConnectors()).rejects.toMatchObject({ retryAfterMs: null });
  });

  it("caps a delay long enough to look like a hang", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        answer(429, { error: { code: "rate_limited", message: "Slow down.", detail: {} } }, {
          "Retry-After": "86400",
        }),
      ),
    );

    await expect(listConnectors()).rejects.toMatchObject({ retryAfterMs: 120_000 });
  });
});

describe("a browser with no connection", () => {
  it("says so, rather than blaming the backend", async () => {
    vi.stubGlobal("navigator", { onLine: false });
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const failure = (await listConnectors().catch((error) => error)) as ApiError;

    expect(failure.code).toBe("offline");
    expect(failure.isOffline).toBe(true);
    expect(failure.isRetryable).toBe(true);
  });

  it("blames the backend when the browser thinks it is connected", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")));

    const failure = (await listConnectors().catch((error) => error)) as ApiError;

    expect(failure.code).toBe("network_error");
    expect(failure.isOffline).toBe(false);
  });
});
