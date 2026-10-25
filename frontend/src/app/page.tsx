import { HealthStatus } from "@/components/HealthStatus";
import { HistoryList } from "@/components/HistoryList";
import { QueryForm } from "@/components/QueryForm";

export default function Home() {
  return (
    <main className="mx-auto flex w-full max-w-3xl flex-1 flex-col gap-8 px-4 py-12">
      <header>
        <h1 className="text-2xl font-semibold tracking-tight">Agentic Policy Analytics</h1>
        <p className="mt-2 text-ink-2">
          Ask a research question about Singapore&apos;s labour market by industry. Agents fetch official data from
          SingStat, Data.gov.sg and MOM, analyse it deterministically, and return only findings that pass evidence
          checks, each with its source.
        </p>
      </header>
      <QueryForm />
      <section aria-label="Recent analyses" className="flex flex-col gap-2">
        <h2 className="text-base font-semibold">Recent analyses</h2>
        <HistoryList />
      </section>
      <footer className="border-t border-border pt-4">
        <HealthStatus />
      </footer>
    </main>
  );
}
