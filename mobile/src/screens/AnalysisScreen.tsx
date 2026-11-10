import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { BrainCircuit, ChevronDown, Clock, Gauge, Loader2, Play, Sparkles } from "lucide-react";

import { api, videoSrc } from "../api";
import SkeletonPlayer, { type SkeletonPlayerHandle } from "../components/SkeletonPlayer";
import StageProgress from "../components/StageProgress";
import { ErrorText, Header, Panel, Screen, timeLabel, wallText } from "../components/ui";
import type { Analysis, Coaching, HybridItem, PoseResult } from "../types";

const POLL_MS = 2000;

const EVIDENCE: Record<HybridItem["evidence_status"], { text: string; className: string }> = {
  measurement_supported: { text: "Measured", className: "bg-lime-400/15 text-lime-300" },
  partially_supported: { text: "Partly measured", className: "bg-amber-400/15 text-amber-300" },
  insufficient_measurement_data: { text: "Not enough data", className: "bg-slate-700 text-slate-300" },
};

function TimeChip({ start, end, onSeek }: { start: number; end?: number; onSeek: (t: number) => void }) {
  return (
    <button type="button" onClick={() => onSeek(start)}
      className="inline-flex items-center gap-1 rounded-full bg-slate-800 px-2.5 py-1 text-xs font-semibold text-lime-300 active:bg-slate-700">
      <Play className="h-3 w-3" />
      {timeLabel(start)}{end !== undefined && `–${timeLabel(end)}`}
    </button>
  );
}

function Collapsible({ title, icon, count, children, defaultOpen = true }: {
  title: string; icon: ReactNode; count?: number; children: ReactNode; defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <Panel>
      <button type="button" onClick={() => setOpen((v) => !v)} className="flex w-full items-center gap-2 text-left">
        {icon}
        <h2 className="flex-1 font-semibold">{title}{count !== undefined && <span className="ml-1.5 text-slate-500">{count}</span>}</h2>
        <ChevronDown className={`h-5 w-5 text-slate-500 transition-transform ${open ? "rotate-180" : ""}`} />
      </button>
      {open && <div className="mt-3">{children}</div>}
    </Panel>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-xl bg-slate-900 p-3">
      <p className="text-[11px] uppercase tracking-wide text-slate-500">{label}</p>
      <p className="mt-0.5 text-lg font-semibold">{value}</p>
    </div>
  );
}

export default function AnalysisScreen({ id, onBack }: { id: string; onBack: () => void }) {
  const player = useRef<SkeletonPlayerHandle>(null);
  const [analysis, setAnalysis] = useState<Analysis | null>(null);
  const [pose, setPose] = useState<PoseResult | null>(null);
  const [hybrid, setHybrid] = useState<HybridItem[] | null>(null);
  const [coaching, setCoaching] = useState<Coaching | null>(null);
  const [coachingBusy, setCoachingBusy] = useState(false);
  const [coachingError, setCoachingError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Poll until the analysis finishes; fetch each result as its stage completes.
  useEffect(() => {
    let cancelled = false;
    let timer = 0;
    let poseLoaded = false;
    let hybridLoaded = false;

    async function tick() {
      try {
        const next = await api.getAnalysis(id);
        if (cancelled) return;
        // Keep the first signed video URL so the <video> element doesn't reload on every poll.
        setAnalysis((prev) => (prev?.video_url ? { ...next, video_url: prev.video_url } : next));
        if (!poseLoaded && next.stages.pose.status === "done") {
          poseLoaded = true;
          api.getPose(id).then((r) => !cancelled && setPose(r)).catch((e: Error) => setError(e.message));
        }
        if (!hybridLoaded && next.stages.hybrid.status === "done") {
          hybridLoaded = true;
          api.getHybrid(id).then((r) => !cancelled && setHybrid(r.hybrid_feedback)).catch((e: Error) => setError(e.message));
        }
        if (next.status === "queued" || next.status === "processing") {
          timer = window.setTimeout(tick, POLL_MS);
        }
      } catch (err) {
        if (cancelled) return;
        setError(err instanceof Error ? err.message : "Couldn't load this analysis.");
        timer = window.setTimeout(tick, POLL_MS * 2);
      }
    }
    void tick();
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
  }, [id]);

  const seek = useCallback((t: number) => player.current?.seekTo(t), []);

  async function requestCoaching() {
    setCoachingBusy(true);
    setCoachingError(null);
    try {
      setCoaching((await api.coaching(id)).coaching);
    } catch (err) {
      setCoachingError(err instanceof Error ? err.message : "AI coaching failed.");
    } finally {
      setCoachingBusy(false);
    }
  }

  if (!analysis) {
    return (
      <Screen>
        <Header title="Analysis" onBack={onBack} />
        {error ? <ErrorText>{error}</ErrorText> : <Loader2 className="mx-auto mt-16 h-7 w-7 animate-spin text-slate-500" />}
      </Screen>
    );
  }

  const running = analysis.status === "queued" || analysis.status === "processing";
  const src = videoSrc(analysis);
  const gemini = analysis.stages.gemini.status;
  const canCoach = analysis.stages.pose.status === "done" && gemini !== "pending" && gemini !== "running";
  const arms = pose?.summary;

  return (
    <Screen>
      <Header title={`${wallText(analysis.wall_angle_deg, analysis.wall_label)} climb`} onBack={onBack} />

      <div className="space-y-4">
        {src ? (
          <SkeletonPlayer ref={player} src={src} overlay={pose?.overlay ?? null} />
        ) : (
          <div className="grid aspect-[9/12] place-items-center rounded-2xl bg-slate-900 text-sm text-slate-500">
            {analysis.status === "failed" ? "No video" : "Preparing video…"}
          </div>
        )}

        {(running || analysis.status === "failed") && (
          <Panel>
            <h2 className="mb-3 flex items-center gap-2 font-semibold">
              {running && <Loader2 className="h-4 w-4 animate-spin text-sky-300" />}
              {running ? "Analyzing" : "Analysis failed"}
            </h2>
            <StageProgress analysis={analysis} />
            {analysis.error && <p className="mt-3 text-sm text-red-300">{analysis.error}</p>}
            {running && <p className="mt-3 text-xs text-slate-500">Usually under a minute. You can leave this screen and come back.</p>}
          </Panel>
        )}
        {error && <ErrorText>{error}</ErrorText>}

        {arms && (
          <Collapsible title="Measurements" icon={<Gauge className="h-5 w-5 text-lime-300" />}>
            <div className="grid grid-cols-2 gap-2">
              <Stat label="Body tracked" value={arms.tracking.pose_coverage === null ? "–" : `${Math.round(arms.tracking.pose_coverage * 100)}%`} />
              <Stat label="Wall" value={wallText(analysis.wall_angle_deg, analysis.wall_label)} />
              <Stat label="Longest deep bend L" value={timeLabel(arms.left_arm.longest_duration)} />
              <Stat label="Longest deep bend R" value={timeLabel(arms.right_arm.longest_duration)} />
              <Stat label="Total deep bend L" value={timeLabel(arms.left_arm.total_duration)} />
              <Stat label="Total deep bend R" value={timeLabel(arms.right_arm.total_duration)} />
            </div>
            <p className="mt-2 text-xs text-slate-500">"Deep bend" = elbow under 90°, measured in 3D.</p>
          </Collapsible>
        )}

        {hybrid && (
          <Collapsible title="Movements" count={hybrid.length} icon={<Sparkles className="h-5 w-5 text-lime-300" />}>
            {hybrid.length === 0 && <p className="text-sm text-slate-400">Gemini couldn't reliably identify movements in this clip.</p>}
            <ul className="space-y-3">
              {hybrid.map((item, index) => (
                <li key={index} className="rounded-xl bg-slate-900 p-3">
                  <div className="mb-1.5 flex flex-wrap items-center gap-2">
                    <TimeChip start={item.start_seconds} end={item.end_seconds} onSeek={seek} />
                    <span className={`rounded-full px-2 py-0.5 text-[11px] font-semibold ${EVIDENCE[item.evidence_status].className}`}>
                      {EVIDENCE[item.evidence_status].text}
                    </span>
                    <span className="text-[11px] text-slate-500">{item.gemini_confidence} confidence</span>
                  </div>
                  <p className="font-medium capitalize">{item.movement_type}</p>
                  <p className="mt-0.5 text-sm text-slate-300">{item.observation}</p>
                  <details className="mt-2 text-xs text-slate-400">
                    <summary className="cursor-pointer text-slate-500">Measurements</summary>
                    <ul className="mt-1 space-y-1">
                      {item.metric_evaluations.map((m) => <li key={m.metric}>• {m.message}</li>)}
                    </ul>
                    <p className="mt-1.5">{item.feedback}</p>
                  </details>
                </li>
              ))}
            </ul>
          </Collapsible>
        )}
        {!running && !hybrid && analysis.stages.gemini.status === "skipped" && (
          <Panel><p className="text-sm text-slate-400">Movement analysis skipped: {analysis.stages.gemini.error}</p></Panel>
        )}

        {pose && pose.feedback.length > 0 && (
          <Collapsible title="Sustained arm bends" count={pose.feedback.length} icon={<Clock className="h-5 w-5 text-lime-300" />} defaultOpen={false}>
            <ul className="space-y-3">
              {pose.feedback.map((item, index) => (
                <li key={index} className="rounded-xl bg-slate-900 p-3 text-sm">
                  <div className="mb-1.5"><TimeChip start={item.start_seconds} end={item.end_seconds} onSeek={seek} /></div>
                  <p className="text-slate-200">{item.observation}</p>
                  <p className="mt-1 text-slate-400">{item.interpretation}</p>
                  <p className="mt-1 text-slate-300"><span className="font-semibold text-lime-300">Try: </span>{item.recommendation}</p>
                </li>
              ))}
            </ul>
          </Collapsible>
        )}

        {pose && (
          <Panel>
            <h2 className="mb-2 flex items-center gap-2 font-semibold"><BrainCircuit className="h-5 w-5 text-lime-300" /> AI coaching</h2>
            {!coaching && (
              <>
                <p className="mb-3 text-sm text-slate-400">
                  {canCoach ? "Get the one thing to fix in this climb, and how." : "Available when movement analysis finishes."}
                </p>
                <button type="button" onClick={() => void requestCoaching()} disabled={!canCoach || coachingBusy}
                  className="flex w-full items-center justify-center gap-2 rounded-2xl bg-slate-800 py-3 font-semibold text-lime-300 active:bg-slate-700 disabled:opacity-40">
                  {coachingBusy && <Loader2 className="h-4 w-4 animate-spin" />}
                  {coachingBusy ? "Generating…" : "Generate AI coaching"}
                </button>
                {coachingError && <div className="mt-2"><ErrorText>{coachingError}</ErrorText></div>}
              </>
            )}
            {coaching && (
              <div className="space-y-2.5 text-sm">
                <div className="rounded-xl bg-amber-400/10 p-3">
                  <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-amber-300">What's going wrong</h3>
                  <p className="text-slate-100">{coaching.issue}</p>
                </div>
                <div className="rounded-xl bg-lime-400/10 p-3">
                  <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-lime-300">How to fix it</h3>
                  <p className="text-slate-100">{coaching.fix}</p>
                </div>
              </div>
            )}
          </Panel>
        )}
      </div>
    </Screen>
  );
}
