import { afterEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
vi.mock("../api/client", () => ({ apiClient: { get } }));

import { getBenchmark } from "../api/benchmark";

afterEach(() => vi.clearAllMocks());

describe("benchmark API client", () => {
  it("requests the route the backend registers, relative to the /api base URL", async () => {
    get.mockResolvedValue({ data: { title: "x" } });
    await expect(getBenchmark()).resolves.toEqual({ title: "x" });
    expect(get).toHaveBeenCalledTimes(1);
    expect(get).toHaveBeenCalledWith("/monitor/benchmark");              // the client prepends VITE_API_BASE_URL (default http://localhost:8000/api): GET /api/monitor/benchmark
  });

  it("lets a failed request reach the page so that it can show its error state", async () => {
    get.mockRejectedValue(new Error("Request failed with status code 404"));
    await expect(getBenchmark()).rejects.toThrow("404");
  });
});
