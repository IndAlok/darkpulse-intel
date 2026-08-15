import { describe, expect, it } from "vitest";
import { intelIdFromGraphNode, resolveIntelId } from "../lib/intel";

describe("resolveIntelId", () => {
  it("strips the graph prefix", () => {
    const intelId = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
    expect(resolveIntelId(`intel:${intelId}`)).toBe(intelId);
    expect(resolveIntelId(intelId)).toBe(intelId);
  });
});

describe("intelIdFromGraphNode", () => {
  it("prefers properties, then the stable node id", () => {
    const intelId = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee";
    expect(
      intelIdFromGraphNode({
        id: `intel:${intelId}`,
        label: "cannabis · adajan",
        type: "IntelRef",
        properties: { intel_id: intelId },
      }),
    ).toBe(intelId);
    expect(
      intelIdFromGraphNode({
        id: `intel:${intelId}`,
        label: "cannabis · adajan",
        type: "IntelRef",
        properties: {},
      }),
    ).toBe(intelId);
  });
});
