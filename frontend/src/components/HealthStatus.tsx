"use client";

import { useEffect, useState } from "react";

import { API_URL } from "@/lib/config";

type Health = {
  status: "ok" | "degraded";
  version: string;
  checks: Record<string, string>;
};

type State =
  | { kind: "loading" }
  | { kind: "ready"; health: Health }
  | { kind: "unreachable"; message: string };

export function HealthStatus({ apiUrl = API_URL }: { apiUrl?: string }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    fetch(`${apiUrl}/api/health`, { signal: controller.signal })
      .then(async (res) => setState({ kind: "ready", health: (await res.json()) as Health }))
      .catch((err: unknown) => {
        if (controller.signal.aborted) return;
        setState({ kind: "unreachable", message: err instanceof Error ? err.message : String(err) });
      });
    return () => controller.abort();
  }, [apiUrl]);

  if (state.kind === "loading") {
    return <p className="text-sm text-zinc-500">Checking API…</p>;
  }
  if (state.kind === "unreachable") {
    return (
      <p role="status" className="text-sm text-red-700">
        API unreachable at {apiUrl}
      </p>
    );
  }
  const { health } = state;
  return (
    <div role="status" className="text-sm">
      <p className={health.status === "ok" ? "text-emerald-700" : "text-amber-700"}>
        API {health.status} (v{health.version})
      </p>
      <ul className="mt-1 text-zinc-600">
        {Object.entries(health.checks).map(([name, result]) => (
          <li key={name}>
            {name}: {result}
          </li>
        ))}
      </ul>
    </div>
  );
}
