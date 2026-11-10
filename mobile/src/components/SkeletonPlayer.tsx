import { forwardRef, useCallback, useEffect, useImperativeHandle, useRef, useState } from "react";
import { Bone, Loader2 } from "lucide-react";

import type { Overlay, OverlayFrame } from "../types";

// Same connections the phase02 OpenCV drawing used (body only, no face).
const CONNECTIONS: [number, number][] = [
  [11, 12], [11, 13], [13, 15], [12, 14], [14, 16],
  [11, 23], [12, 24], [23, 24], [23, 25], [25, 27],
  [27, 29], [29, 31], [24, 26], [26, 28], [28, 30], [30, 32],
];
const LEFT = new Set([11, 13, 15, 23, 25, 27, 29, 31]);
const VISIBLE = 0.5;

export interface SkeletonPlayerHandle {
  seekTo: (seconds: number) => void;
}

interface Props {
  src: string;
  overlay: Overlay | null;
}

/** Index of the overlay frame at or just before `time` (binary search). */
function frameAt(frames: OverlayFrame[], time: number): OverlayFrame | null {
  if (!frames.length) return null;
  let lo = 0;
  let hi = frames.length - 1;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (frames[mid].t <= time + 0.001) lo = mid;
    else hi = mid - 1;
  }
  const frame = frames[lo];
  // Don't hold a stale pose across a long gap (e.g. before the first frame).
  return Math.abs(frame.t - time) < 0.2 ? frame : null;
}

const SkeletonPlayer = forwardRef<SkeletonPlayerHandle, Props>(function SkeletonPlayer({ src, overlay }, ref) {
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [showSkeleton, setShowSkeleton] = useState(true);
  const [loading, setLoading] = useState(true);
  const [failed, setFailed] = useState(false);

  // iPhone Safari doesn't load any video data until the user presses play,
  // so "loaded" events may never fire on their own. Never keep the spinner
  // up for more than a few seconds, and it never blocks taps (see below).
  useEffect(() => {
    setLoading(true);
    setFailed(false);
    const timer = window.setTimeout(() => setLoading(false), 4000);
    return () => window.clearTimeout(timer);
  }, [src]);

  useImperativeHandle(ref, () => ({
    seekTo(seconds: number) {
      const video = videoRef.current;
      if (!video) return;
      video.currentTime = Math.max(0, seconds);
      video.scrollIntoView({ behavior: "smooth", block: "center" });
      void video.play().catch(() => undefined);
    },
  }));

  const draw = useCallback(
    (time: number) => {
      const video = videoRef.current;
      const canvas = canvasRef.current;
      if (!video || !canvas) return;

      // Match the canvas to the element size (in device pixels for sharp lines).
      const dpr = window.devicePixelRatio || 1;
      const cssWidth = video.clientWidth;
      const cssHeight = video.clientHeight;
      if (canvas.width !== Math.round(cssWidth * dpr) || canvas.height !== Math.round(cssHeight * dpr)) {
        canvas.width = Math.round(cssWidth * dpr);
        canvas.height = Math.round(cssHeight * dpr);
      }
      const ctx = canvas.getContext("2d");
      if (!ctx) return;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cssWidth, cssHeight);
      if (!showSkeleton || !overlay || !video.videoWidth) return;

      const frame = frameAt(overlay.frames, time);
      if (!frame?.p) return;

      // The video is letterboxed (object-fit: contain): find the picture's rectangle.
      const scale = Math.min(cssWidth / video.videoWidth, cssHeight / video.videoHeight);
      const width = video.videoWidth * scale;
      const height = video.videoHeight * scale;
      const offsetX = (cssWidth - width) / 2;
      const offsetY = (cssHeight - height) / 2;
      const p = frame.p;
      const point = (i: number) => [offsetX + p[i * 3] * width, offsetY + p[i * 3 + 1] * height] as const;
      const visible = (i: number) => p[i * 3 + 2] >= VISIBLE;

      ctx.lineCap = "round";
      ctx.lineWidth = Math.max(2, width / 180);
      for (const [a, b] of CONNECTIONS) {
        if (!visible(a) || !visible(b)) continue;
        const [x1, y1] = point(a);
        const [x2, y2] = point(b);
        ctx.strokeStyle = LEFT.has(a) && LEFT.has(b) ? "#a3e635" : LEFT.has(a) || LEFT.has(b) ? "#e2e8f0" : "#38bdf8";
        ctx.beginPath();
        ctx.moveTo(x1, y1);
        ctx.lineTo(x2, y2);
        ctx.stroke();
      }
      const radius = Math.max(2.5, width / 140);
      for (let i = 11; i < 33; i++) {
        if (!visible(i)) continue;
        const [x, y] = point(i);
        ctx.fillStyle = "#f8fafc";
        ctx.beginPath();
        ctx.arc(x, y, radius, 0, Math.PI * 2);
        ctx.fill();
      }
    },
    [overlay, showSkeleton],
  );

  // Redraw in sync with the decoded frame when the browser supports it
  // (Safari 15.4+, Chrome); otherwise fall back to an animation loop.
  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    let cancelled = false;
    let handle = 0;
    const hasFrameCallback = "requestVideoFrameCallback" in HTMLVideoElement.prototype;

    const onFrame = (_now: number, metadata: { mediaTime: number }) => {
      if (cancelled) return;
      draw(metadata.mediaTime);
      handle = video.requestVideoFrameCallback(onFrame);
    };
    const onAnimation = () => {
      if (cancelled) return;
      draw(video.currentTime);
      handle = requestAnimationFrame(onAnimation);
    };

    if (hasFrameCallback) handle = video.requestVideoFrameCallback(onFrame);
    else handle = requestAnimationFrame(onAnimation);

    // Paused seeks and resizes don't always produce a frame callback.
    const redraw = () => draw(video.currentTime);
    video.addEventListener("seeked", redraw);
    video.addEventListener("loadeddata", redraw);
    window.addEventListener("resize", redraw);
    redraw();

    return () => {
      cancelled = true;
      if (hasFrameCallback) video.cancelVideoFrameCallback(handle);
      else cancelAnimationFrame(handle);
      video.removeEventListener("seeked", redraw);
      video.removeEventListener("loadeddata", redraw);
      window.removeEventListener("resize", redraw);
    };
  }, [draw]);

  return (
    <div className="space-y-2">
      <div className="relative overflow-hidden rounded-2xl bg-black">
        <video
          ref={videoRef}
          src={src}
          className="block max-h-[70vh] w-full object-contain"
          controls
          playsInline
          muted
          loop
          preload="auto"
          onLoadedMetadata={() => setLoading(false)}
          onLoadedData={() => setLoading(false)}
          onCanPlay={() => setLoading(false)}
          onPlaying={() => setLoading(false)}
          onError={() => {
            setLoading(false);
            setFailed(true);
          }}
        />
        <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full" aria-hidden />
        {loading && (
          <div className="pointer-events-none absolute inset-0 grid place-items-center">
            <Loader2 className="h-8 w-8 animate-spin text-lime-300" />
          </div>
        )}
        {failed && (
          <div className="pointer-events-none absolute inset-0 grid place-items-center bg-black/70 p-6 text-center text-sm text-slate-300">
            The video couldn't load. The link may have expired: go back and reopen this analysis.
          </div>
        )}
      </div>
      <div className="flex items-center justify-between">
        <span className="text-xs text-slate-400">
          {overlay ? "Lime = left side · Blue = right side" : "Skeleton appears when pose tracking finishes"}
        </span>
        <button
          type="button"
          onClick={() => setShowSkeleton((v) => !v)}
          disabled={!overlay}
          aria-pressed={showSkeleton}
          className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs font-semibold transition-colors disabled:opacity-40 ${
            showSkeleton && overlay ? "bg-lime-400 text-slate-950" : "bg-slate-800 text-slate-200"
          }`}
        >
          <Bone className="h-3.5 w-3.5" />
          Skeleton {showSkeleton ? "on" : "off"}
        </button>
      </div>
    </div>
  );
});

export default SkeletonPlayer;
