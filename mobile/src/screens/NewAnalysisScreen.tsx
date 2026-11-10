import { useEffect, useRef, useState } from "react";
import { Camera, Lightbulb, Upload } from "lucide-react";

import { uploadAnalysis } from "../api";
import WallAnglePicker from "../components/WallAnglePicker";
import { DurationNotice, ErrorText, Header, Panel, PrimaryButton, Screen } from "../components/ui";

interface Props {
  maxSeconds: number;
  onBack: () => void;
  onCreated: (id: string) => void;
}

/** Read a video's length in the browser. Resolves null if it can't be read. */
function readDuration(url: string): Promise<number | null> {
  return new Promise((resolve) => {
    const probe = document.createElement("video");
    probe.preload = "metadata";
    probe.muted = true;
    const done = (value: number | null) => {
      probe.removeAttribute("src");
      resolve(value);
    };
    probe.onloadedmetadata = () => done(Number.isFinite(probe.duration) ? probe.duration : null);
    probe.onerror = () => done(null);
    setTimeout(() => done(null), 8000);
    probe.src = url;
  });
}

export default function NewAnalysisScreen({ maxSeconds, onBack, onCreated }: Props) {
  const recordInput = useRef<HTMLInputElement>(null);
  const uploadInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [duration, setDuration] = useState<number | null>(null);
  const [checking, setChecking] = useState(false);
  const [wallAngle, setWallAngle] = useState(0);
  const [wallLabel, setWallLabel] = useState("Vertical");
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => () => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
  }, [previewUrl]);

  async function choose(selected: File | undefined) {
    if (!selected) return;
    setError(null);
    const url = URL.createObjectURL(selected);
    setFile(selected);
    setPreviewUrl(url);
    setDuration(null);
    setChecking(true);
    setDuration(await readDuration(url));
    setChecking(false);
  }

  // Small allowance for rounding, matching the server's check.
  const tooLong = duration !== null && duration > maxSeconds + 0.5;

  async function submit() {
    if (!file || tooLong) return;
    setError(null);
    setProgress(0);
    try {
      const analysis = await uploadAnalysis(file, wallAngle, wallLabel, setProgress);
      onCreated(analysis.id);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Upload failed.");
      setProgress(null);
    }
  }

  const uploading = progress !== null;

  return (
    <Screen>
      <Header title="New analysis" onBack={uploading ? undefined : onBack} />

      <div className="space-y-4">
        <DurationNotice seconds={maxSeconds} />

        <Panel>
          <h2 className="mb-3 font-semibold">1. Your climb</h2>
          {/* capture opens the camera directly; the second input opens the library. */}
          <input ref={recordInput} type="file" accept="video/*" capture="environment" className="sr-only"
            onChange={(e) => void choose(e.target.files?.[0])} />
          <input ref={uploadInput} type="file" accept="video/*" className="sr-only"
            onChange={(e) => void choose(e.target.files?.[0])} />

          <div className="grid grid-cols-2 gap-2">
            <button type="button" disabled={uploading} onClick={() => recordInput.current?.click()}
              className="flex flex-col items-center gap-1.5 rounded-2xl bg-slate-800 py-4 font-semibold active:bg-slate-700 disabled:opacity-40">
              <Camera className="h-6 w-6 text-lime-300" /> Record
            </button>
            <button type="button" disabled={uploading} onClick={() => uploadInput.current?.click()}
              className="flex flex-col items-center gap-1.5 rounded-2xl bg-slate-800 py-4 font-semibold active:bg-slate-700 disabled:opacity-40">
              <Upload className="h-6 w-6 text-lime-300" /> Upload
            </button>
          </div>

          {previewUrl && (
            <div className="mt-3 space-y-2">
              <video src={previewUrl} className="max-h-72 w-full rounded-xl bg-black object-contain" controls playsInline muted />
              <p className={`text-sm ${tooLong ? "text-red-300" : "text-slate-400"}`}>
                {checking
                  ? "Checking length…"
                  : duration === null
                    ? "Couldn't preview this clip here. It will be checked after upload."
                    : tooLong
                    ? `This clip is ${duration.toFixed(1)} s. Please trim it to ${maxSeconds} seconds or less.`
                      : `${duration.toFixed(1)} s · ${(file!.size / 1024 / 1024).toFixed(1)} MB`}
              </p>
            </div>
          )}
        </Panel>

        <Panel>
          <h2 className="mb-1 font-semibold">2. Wall angle</h2>
          <p className="mb-3 text-xs text-slate-400">Used to interpret your hip movement and arm bends.</p>
          <WallAnglePicker angle={wallAngle} label={wallLabel}
            onChange={(angle, label) => { setWallAngle(angle); setWallLabel(label); }} />
        </Panel>

        <div className="flex gap-3 rounded-2xl bg-slate-900 p-3.5 text-sm text-slate-300">
          <Lightbulb className="mt-0.5 h-5 w-5 shrink-0 text-lime-300" />
          <p>For the best tracking: hold the phone level, stand behind the climber, and keep their whole body in frame.</p>
        </div>

        {error && <ErrorText>{error}</ErrorText>}

        <PrimaryButton onClick={() => void submit()} disabled={!file || tooLong || checking} busy={uploading}>
          {uploading
            ? progress! < 1 ? `Uploading ${Math.round(progress! * 100)}%` : "Starting analysis…"
            : "Analyze climb"}
        </PrimaryButton>
        {uploading && <p className="text-center text-xs text-slate-500">Keep the app open until the upload finishes.</p>}
      </div>
    </Screen>
  );
}
