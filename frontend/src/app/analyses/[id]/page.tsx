import { AnalysisView } from "@/components/AnalysisView";

export default async function Page(props: PageProps<"/analyses/[id]">) {
  const { id } = await props.params;
  return (
    <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">
      {/* Keyed by id so a new analysis starts with a fresh event stream. */}
      <AnalysisView key={id} id={id} />
    </main>
  );
}
