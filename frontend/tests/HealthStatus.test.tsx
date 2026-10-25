import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { HealthStatus } from "@/components/HealthStatus";

afterEach(() => vi.unstubAllGlobals());

function stubFetch(impl: () => Promise<Response>) {
  vi.stubGlobal("fetch", vi.fn(impl));
}

describe("HealthStatus", () => {
  it("shows each dependency check when the API is healthy", async () => {
    stubFetch(async () =>
      Response.json({ status: "ok", version: "0.1.0", checks: { database: "ok", redis: "ok" } }),
    );
    render(<HealthStatus apiUrl="http://api.test" />);
    expect(await screen.findByText("API ok (v0.1.0)")).toBeInTheDocument();
    expect(screen.getByText("redis: ok")).toBeInTheDocument();
  });

  it("surfaces a degraded dependency from a 503 response", async () => {
    stubFetch(async () =>
      Response.json(
        { status: "degraded", version: "0.1.0", checks: { database: "ok", redis: "error: ConnectionError" } },
        { status: 503 },
      ),
    );
    render(<HealthStatus apiUrl="http://api.test" />);
    expect(await screen.findByText("API degraded (v0.1.0)")).toBeInTheDocument();
    expect(screen.getByText("redis: error: ConnectionError")).toBeInTheDocument();
  });

  it("reports an unreachable API", async () => {
    stubFetch(async () => {
      throw new TypeError("Failed to fetch");
    });
    render(<HealthStatus apiUrl="http://api.test" />);
    expect(await screen.findByText("API unreachable at http://api.test")).toBeInTheDocument();
  });
});
