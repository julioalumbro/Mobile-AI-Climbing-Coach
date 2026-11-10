import type { ReactNode } from "react";
import { ChevronLeft, Info, Loader2 } from "lucide-react";

export function Screen({ children }: { children: ReactNode }) {
  return (
    <div className="mx-auto min-h-dvh w-full max-w-xl px-4 pb-[calc(env(safe-area-inset-bottom)+6rem)] pt-[calc(env(safe-area-inset-top)+1rem)]">
      {children}
    </div>
  );
}

export function Header({ title, onBack, right }: { title: string; onBack?: () => void; right?: ReactNode }) {
  return (
    <header className="mb-5 flex items-center gap-2">
      {onBack && (
        <button type="button" onClick={onBack} aria-label="Back" className="-ml-2 rounded-full p-2 text-slate-300 active:bg-slate-800">
          <ChevronLeft className="h-6 w-6" />
        </button>
      )}
      <h1 className="flex-1 truncate text-xl font-bold tracking-tight">{title}</h1>
      {right}
    </header>
  );
}

export function Panel({ children, className = "" }: { children: ReactNode; className?: string }) {
  return <section className={`panel p-4 ${className}`}>{children}</section>;
}

/** The 20-second notice shown wherever a tester can pick or record a video. */
export function DurationNotice({ seconds }: { seconds: number }) {
  return (
    <div role="note" className="flex items-start gap-3 rounded-2xl border border-amber-400/40 bg-amber-400/10 p-3.5 text-amber-100">
      <Info className="mt-0.5 h-5 w-5 shrink-0 text-amber-300" />
      <p className="text-sm">
        <span className="font-semibold">Upload video up to {seconds} seconds long.</span>{" "}
        Trim longer clips to the climb itself before uploading.
      </p>
    </div>
  );
}

export function PrimaryButton({
  children, onClick, disabled, busy, type = "button",
}: { children: ReactNode; onClick?: () => void; disabled?: boolean; busy?: boolean; type?: "button" | "submit" }) {
  return (
    <button
      type={type}
      onClick={onClick}
      disabled={disabled || busy}
      className="flex w-full items-center justify-center gap-2 rounded-2xl bg-lime-400 px-4 py-3.5 font-semibold text-slate-950 transition active:scale-[0.99] disabled:opacity-40"
    >
      {busy && <Loader2 className="h-5 w-5 animate-spin" />}
      {children}
    </button>
  );
}

export function ErrorText({ children }: { children: ReactNode }) {
  return <p role="alert" className="rounded-xl bg-red-500/10 px-3 py-2 text-sm text-red-300">{children}</p>;
}

export function timeLabel(seconds: number) {
  return `${seconds.toFixed(1)}s`;
}

export function formatDate(iso: string) {
  const date = new Date(iso);
  return date.toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" });
}

export function wallText(angle: number, label?: string | null) {
  if (label) return label;
  if (angle === 0) return "Vertical";
  return angle < 0 ? `Slab ${Math.abs(angle)}°` : `${angle}° overhang`;
}
