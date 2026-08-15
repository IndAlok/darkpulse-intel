import { beforeEach, describe, expect, it, vi } from "vitest";
import { exportApi, intelApi } from "../lib/api";

describe("API adapters", () => {
  beforeEach(() => { vi.restoreAllMocks(); });

  it("encodes feed filters and returns the API envelope", async () => {
    const fetchMock = vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response(JSON.stringify({ data: [], pagination: { cursor: null, limit: 25, total: 0 } }), { status: 200, headers: { "Content-Type": "application/json" } }));
    await expect(intelApi.list({ q: "ગુજરાતી text", band: "high" })).resolves.toMatchObject({ data: [] });
    expect(fetchMock.mock.calls[0][0].toString()).toContain("q=%E0%AA%97%E0%AB%81%E0%AA%9C%E0%AA%B0%E0%AA%BE%E0%AA%A4%E0%AB%80+text");
  });

  it("downloads exports as a Blob and reads the evidence seal header", async () => {
    vi.spyOn(globalThis, "fetch").mockResolvedValue(new Response("report", { status: 200, headers: { "Content-Type": "application/pdf", "Content-Disposition": "attachment; filename=report.pdf", "X-DarkPulse-Evidence-Seal": "abc123" } }));
    const result = await exportApi.report("pdf", ["intel-1"]);
    expect(result.filename).toBe("report.pdf"); expect(result.evidenceSeal).toBe("abc123"); expect(await result.blob.text()).toBe("report");
  });
});
