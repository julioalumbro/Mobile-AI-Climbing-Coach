import { CheckCircle2, CircleDashed, Loader2, MinusCircle, XCircle } from "lucide-react";

import type { Analysis, StageName, StageStatus } from "../types";

const STEPS: { key: StageName; label: string }[] = [
  { key: "normalize", label: "Preparing video" },
  { key: "pose", label: "Tracking your body (MediaPipe)" },
  { key: "gemini", label: "Watching the climb (Gemini)" },
  { key: "hybrid", label: "Matching moves with measurements" },
];

function Icon({ status }: { status: StageStatus }) {
  if (status === "done") return <CheckCircle2 className="h-5 w-5 text-lime-400" />;
  if (status === "running") return <Loader2 className="h-5 w-5 animate-spin text-sky-300" />;
  if (status === "failed") return <XCircle className="h-5 w-5 text-red-400" />;
  if (status === "skipped") return <MinusCircle className="h-5 w-5 text-slate-500" />;
  return <CircleDashed className="h-5 w-5 text-slate-600" />;
}

export default function StageProgress({ analysis }: { analysis: Analysis }) {
  return (
    <ol className="space-y-2.5">
      {STEPS.map(({ key, label }) => {
        const stage = analysis.stages[key];
        return (
          <li key={key} className="flex items-start gap-3">
            <Icon status={stage.status} />
            <div className="min-w-0">
              <p className={`text-sm ${stage.status === "pending" ? "text-slate-500" : "text-slate-100"}`}>{label}</p>
              {stage.error && stage.status !== "done" && <p className="text-xs text-slate-400">{stage.error}</p>}
            </div>
          </li>
        );
      })}
    </ol>
  );
}
