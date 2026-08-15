import { describe, expect, it, vi } from "vitest";
import { renderHook, waitFor } from "@testing-library/react";
import { useApi } from "../hooks";

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason?: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

describe("useApi", () => {
  it("ignores stale responses when a newer request completes first", async () => {
    const first = deferred<string>();
    const second = deferred<string>();
    const request = vi
      .fn<() => Promise<string>>()
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);

    const { result, rerender } = renderHook(
      ({ key }: { key: string }) => useApi(request, key),
      { initialProps: { key: "a" } },
    );

    expect(result.current.loading).toBe(true);

    rerender({ key: "b" });
    second.resolve("fresh");
    await waitFor(() => expect(result.current.data).toBe("fresh"));

    first.resolve("stale");
    await new Promise((done) => setTimeout(done, 10));
    expect(result.current.data).toBe("fresh");
    expect(result.current.error).toBeNull();
    expect(result.current.loading).toBe(false);
  });

  it("surfaces request failures as error strings", async () => {
    const failing = deferred<string>();
    const request = vi.fn<() => Promise<string>>().mockReturnValue(failing.promise);
    const { result } = renderHook(() => useApi(request));
    failing.reject(new Error("Unable to reach the API"));
    await waitFor(() => expect(result.current.error).toBe("Unable to reach the API"));
    expect(result.current.loading).toBe(false);
  });

  it("reloads on demand", async () => {
    const request = vi
      .fn<() => Promise<string>>()
      .mockResolvedValueOnce("one")
      .mockResolvedValueOnce("two");
    const { result } = renderHook(() => useApi(request));
    await waitFor(() => expect(result.current.data).toBe("one"));
    await result.current.reload();
    await waitFor(() => expect(result.current.data).toBe("two"));
  });
});
