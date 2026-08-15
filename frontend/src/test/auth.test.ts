import { beforeEach, describe, expect, it, vi } from "vitest";
import { authApi, searchApi, wsUrl } from "../lib/api";
import { setAccessToken } from "../lib/auth";

describe("auth and search adapters", () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    sessionStorage.clear();
  });

  it("exchanges a token through login and stores nothing in public config", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(
        JSON.stringify({ data: { subject: "analyst-1", role: "analyst", token: "secret-token" } }),
        { status: 200, headers: { "Content-Type": "application/json" } },
      ),
    );
    await expect(authApi.login("secret-token")).resolves.toMatchObject({
      data: { subject: "analyst-1", role: "analyst" },
    });
    expect(String(fetchMock.mock.calls[0][0])).toContain("/auth/login");
  });

  it("sends hinglish as a first-class search language", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(
      new Response(JSON.stringify({ data: [] }), {
        status: 200,
        headers: { "Content-Type": "application/json" },
      }),
    );
    await searchApi.search("maal", "hinglish");
    expect(String(fetchMock.mock.calls[0][0])).toContain("lang=hinglish");
  });

  it("builds the alert websocket from the current origin", () => {
    setAccessToken("session-token");
    const url = wsUrl();
    expect(url.startsWith("ws://") || url.startsWith("wss://")).toBe(true);
    expect(url).toContain("/api/v1/alerts/ws");
    expect(url).toContain("access_token=session-token");
    expect(url).not.toContain("railway.internal");
  });
});
