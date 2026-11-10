import { useState, type FormEvent } from "react";
import { Mountain } from "lucide-react";

import { api, ApiError, setInviteCode } from "../api";
import { ErrorText, PrimaryButton, Screen } from "../components/ui";
import type { Me } from "../types";

export default function InviteScreen({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit(event: FormEvent) {
    event.preventDefault();
    const trimmed = code.trim().toUpperCase();
    if (!trimmed) return;
    setBusy(true);
    setError(null);
    try {
      const me = await api.me(trimmed);
      setInviteCode(trimmed);
      onSignedIn(me);
    } catch (err) {
      setError(err instanceof ApiError && err.status === 401
        ? "That invite code isn't valid. Check it and try again."
        : err instanceof Error ? err.message : "Something went wrong.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Screen>
      <div className="flex min-h-[80dvh] flex-col justify-center">
        <div className="mb-8 flex items-center gap-3">
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-lime-400 text-slate-950">
            <Mountain className="h-7 w-7" />
          </div>
          <div>
            <h1 className="text-2xl font-bold tracking-tight">AI Climbing Coach</h1>
            <p className="text-sm text-slate-400">Private beta</p>
          </div>
        </div>

        <form onSubmit={submit} className="space-y-4">
          <label className="block">
            <span className="mb-1.5 block text-sm font-medium text-slate-300">Invite code</span>
            <input
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="CLIMB-XXXX-XXXX-XXXX"
              autoCapitalize="characters"
              autoComplete="off"
              autoCorrect="off"
              spellCheck={false}
              className="w-full rounded-2xl border border-slate-700 bg-slate-900 px-4 py-3.5 font-mono text-base tracking-wide text-white placeholder:text-slate-600 focus:border-lime-400 focus:outline-none"
            />
          </label>
          {error && <ErrorText>{error}</ErrorText>}
          <PrimaryButton type="submit" busy={busy} disabled={!code.trim()}>Continue</PrimaryButton>
        </form>

        <p className="mt-6 text-xs text-slate-500">
          Experimental tool for reviewing your climbing movement. It isn't professional coaching or safety advice.
        </p>
      </div>
    </Screen>
  );
}
