import { Suspense } from "react";
import { RunScreen } from "@/components/RunScreen";

export default function RunPage({ params }: PageProps<"/runs/[runId]">) {
  return (
    <Suspense fallback={<div className="p-8 text-muted">Loading run…</div>}>
      {params.then(({ runId }) => (
        <RunScreen runId={decodeURIComponent(runId)} />
      ))}
    </Suspense>
  );
}
