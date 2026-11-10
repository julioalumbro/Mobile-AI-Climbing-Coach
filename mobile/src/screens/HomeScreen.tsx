import { useEffect, useState } from "react";
import { ChevronRight, Loader2, LogOut, Plus } from "lucide-react";

import { api } from "../api";
import InstallHint from "../components/InstallHint";
import { ErrorText, formatDate, Header, Screen, wallText } from "../components/ui";
import type { Analysis, Me } from "../types";

const STATUS: Record<Analysis["status"], { text: string; className: string }> = {
  queued: { text: "Queued", className: "bg-slate-700 text-slate-200" },
  processing: { text: "Analyzing", className: "bg-sky-500/20 text-sky-300" },
  completed: { text: "Ready", className: "bg-lime-400/15 text-lime-300" },
  failed: { text: "Failed", className: "bg-red-500/15 text-red-300" },
  expired: { text: "Expired", className: "bg-slate-800 text-slate-500" },
};

interface Props {
  me: Me;
  onNew: () => void;
  onOpen: (id: string) => void;
  onSignOut: () => void;
}

export default function HomeScreen({ me, onNew, onOpen, onSignOut }: Props) {
  const [analyses, setAnalyses] = useState<Analysis[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api.listAnalyses().then(setAnalyses).catch((err: Error) => setError(err.message));
  }, []);

  const limitReached = me.analyses_today >= me.daily_analysis_limit;

  return (
    <Screen>
      <Header
        title={`Hi, ${me.name}`}
        right={
          <button type="button" onClick={onSignOut} aria-label="Sign out" className="rounded-full p-2 text-slate-400 active:bg-slate-800">
            <LogOut className="h-5 w-5" />
          </button>
        }
      />
      <InstallHint />

      <p className="mb-4 text-sm text-slate-400">
        {me.analyses_today} of {me.daily_analysis_limit} analyses used today
        {!me.ai_budget_available && " · AI feedback is paused until tomorrow (beta budget reached)"}
      </p>

      <h2 className="mb-2 text-sm font-semibold uppercase tracking-wider text-slate-500">Your climbs</h2>
      {error && <ErrorText>{error}</ErrorText>}
      {!analyses && !error && <Loader2 className="mx-auto mt-10 h-6 w-6 animate-spin text-slate-500" />}
      {analyses?.length === 0 && (
        <div className="panel p-6 text-center text-sm text-slate-400">
          No climbs yet. Record or upload a short clip to get started.
        </div>
      )}
      <ul className="space-y-2">
        {analyses?.map((analysis) => (
          <li key={analysis.id}>
            <button
              type="button"
              onClick={() => onOpen(analysis.id)}
              disabled={analysis.status === "expired"}
              className="panel flex w-full items-center gap-3 p-3.5 text-left active:bg-slate-800/60 disabled:opacity-60"
            >
              <div className="min-w-0 flex-1">
                <p className="truncate font-medium">{wallText(analysis.wall_angle_deg, analysis.wall_label)} · {analysis.duration_seconds?.toFixed(0)}s</p>
                <p className="text-xs text-slate-400">{formatDate(analysis.created_at)}</p>
              </div>
              <span className={`rounded-full px-2.5 py-1 text-xs font-semibold ${STATUS[analysis.status].className}`}>
                {STATUS[analysis.status].text}
              </span>
              <ChevronRight className="h-4 w-4 text-slate-600" />
            </button>
          </li>
        ))}
      </ul>

      <div className="fixed inset-x-0 bottom-0 bg-gradient-to-t from-[#090d15] via-[#090d15] to-transparent px-4 pb-[calc(env(safe-area-inset-bottom)+1rem)] pt-6">
        <div className="mx-auto max-w-xl">
          <button
            type="button"
            onClick={onNew}
            disabled={limitReached}
            className="flex w-full items-center justify-center gap-2 rounded-2xl bg-lime-400 py-4 text-base font-bold text-slate-950 shadow-lg shadow-lime-400/10 active:scale-[0.99] disabled:opacity-40"
          >
            <Plus className="h-5 w-5" />
            {limitReached ? "Daily limit reached" : "New analysis"}
          </button>
        </div>
      </div>
    </Screen>
  );
}
