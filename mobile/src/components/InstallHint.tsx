import { useEffect, useState } from "react";
import { Download, Share, X } from "lucide-react";

interface InstallPromptEvent extends Event {
  prompt: () => Promise<void>;
}

const DISMISS_KEY = "climbcoach.installHintDismissed";

function isStandalone() {
  return (
    window.matchMedia("(display-mode: standalone)").matches ||
    (navigator as Navigator & { standalone?: boolean }).standalone === true
  );
}

function isIos() {
  return /iphone|ipad|ipod/i.test(navigator.userAgent) ||
    (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
}

/** "Add to Home Screen" help: iOS needs manual steps, Android/Chrome has a prompt. */
export default function InstallHint() {
  const [prompt, setPrompt] = useState<InstallPromptEvent | null>(null);
  const [dismissed, setDismissed] = useState(() => {
    try {
      return localStorage.getItem(DISMISS_KEY) === "1";
    } catch {
      return false;
    }
  });

  useEffect(() => {
    const onPrompt = (event: Event) => {
      event.preventDefault();
      setPrompt(event as InstallPromptEvent);
    };
    window.addEventListener("beforeinstallprompt", onPrompt);
    return () => window.removeEventListener("beforeinstallprompt", onPrompt);
  }, []);

  if (dismissed || isStandalone() || (!isIos() && !prompt)) return null;

  const dismiss = () => {
    setDismissed(true);
    try {
      localStorage.setItem(DISMISS_KEY, "1");
    } catch {
      // ignore
    }
  };

  return (
    <div className="relative mb-4 flex items-start gap-3 rounded-2xl border border-sky-400/30 bg-sky-400/10 p-3.5 pr-10 text-sm text-sky-100">
      {isIos() ? <Share className="mt-0.5 h-5 w-5 shrink-0 text-sky-300" /> : <Download className="mt-0.5 h-5 w-5 shrink-0 text-sky-300" />}
      {isIos() ? (
        <p>Install the app: tap <span className="font-semibold">Share</span>, then <span className="font-semibold">Add to Home Screen</span>.</p>
      ) : (
        <button type="button" className="text-left font-semibold underline" onClick={() => void prompt?.prompt()}>
          Install the app on your home screen
        </button>
      )}
      <button type="button" onClick={dismiss} aria-label="Dismiss" className="absolute right-2 top-2 p-1.5 text-sky-200/70">
        <X className="h-4 w-4" />
      </button>
    </div>
  );
}
