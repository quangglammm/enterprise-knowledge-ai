import { afterEach, describe, expect, it, vi } from "vitest";

import { ApiError, askQuestion, getJob, identityHeaders } from "./api";

const IDENTITY = { tenant: "bamboo-harbor", user: "an", groups: "all-staff, hr" };

afterEach(() => vi.unstubAllGlobals());

function respond(status: number, body: unknown) {
  const fetchMock = vi.fn().mockResolvedValue(
    new Response(JSON.stringify(body), { status, headers: { "content-type": "application/json" } }),
  );
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

describe("identityHeaders", () => {
  it("sends the development identity headers with tidy groups", () => {
    expect(identityHeaders(IDENTITY)).toEqual({
      "X-Tenant-ID": "bamboo-harbor",
      "X-User-ID": "an",
      "X-User-Groups": "all-staff,hr",
    });
  });
});

describe("askQuestion", () => {
  it("posts the question and mode through the API proxy", async () => {
    const fetchMock = respond(200, { status: "answered", mode: "workflow" });

    const result = await askQuestion("Bao nhiêu ngày phép?", "workflow", IDENTITY);

    expect(result.answer.mode).toBe("workflow");
    expect(result.latencyMs).toBeGreaterThanOrEqual(0);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/v1/answers");
    expect(JSON.parse(init.body)).toEqual({ question: "Bao nhiêu ngày phép?", mode: "workflow" });
    expect(init.headers["X-Tenant-ID"]).toBe("bamboo-harbor");
  });

  it("turns the API's error body into a typed error", async () => {
    respond(504, { error: { category: "workflow_timeout", message: "too slow", request_id: "r1" } });

    const error = await askQuestion("q", "workflow", IDENTITY).catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect(error).toMatchObject({ status: 504, category: "workflow_timeout", requestId: "r1" });
  });

  it("reports an unreachable API plainly", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("fetch failed")));

    const error = await askQuestion("q", "direct", IDENTITY).catch((e: unknown) => e);

    expect(error).toMatchObject({ status: 0, category: "api_unreachable" });
  });
});

describe("getJob", () => {
  it("escapes the job ID in the path", async () => {
    const fetchMock = respond(200, { id: "a/b", status: "queued" });

    await getJob("a/b", IDENTITY);

    expect(fetchMock.mock.calls[0][0]).toBe("/api/v1/jobs/a%2Fb");
  });
});
