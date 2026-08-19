import { describe, expect, it } from "vitest";

import { forecastEventsUrl } from "@/lib/api";

describe("the progress stream URL", () => {
  it("carries no token when there is no session", () => {
    expect(forecastEventsUrl("run-1")).not.toContain("access_token");
    expect(forecastEventsUrl("run-1", null)).not.toContain("access_token");
  });

  it("carries the session when there is one", () => {
    expect(forecastEventsUrl("run-1", "abc.def.ghi")).toContain("access_token=abc.def.ghi");
  });

  it("escapes a token rather than pasting it into the query", () => {
    // EventSource cannot send headers, so this is the one place a token goes
    // into a URL. A token that is not escaped can end the query and start
    // another parameter.
    const url = forecastEventsUrl("run-1", "a&b=c");
    expect(url).toContain("access_token=a%26b%3Dc");
    expect(url.split("?")[1]?.split("&")).toHaveLength(1);
  });
});
