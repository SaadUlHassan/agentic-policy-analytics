import { HealthStatus } from "@/components/HealthStatus";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-6 px-4 py-16">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Agentic Policy Analytics</h1>
        <p className="mt-2 text-zinc-600">
          Ask a research question about Singapore&apos;s labour market. Agents extract official data,
          analyse it deterministically, and return verified, cited findings.
        </p>
      </header>
      <section aria-label="System status">
        <HealthStatus />
      </section>
    </main>
  );
}
