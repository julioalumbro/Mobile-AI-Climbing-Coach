import { useState } from "react";

const PRESETS = [
  { label: "Slab", angle: -10 },
  { label: "Vertical", angle: 0 },
  { label: "15°", angle: 15 },
  { label: "30°", angle: 30 },
  { label: "40°", angle: 40 },
  { label: "50°", angle: 50 },
];

interface Props {
  angle: number;
  label: string;
  onChange: (angle: number, label: string) => void;
}

export function customLabel(angle: number) {
  if (angle === 0) return "Vertical";
  return angle < 0 ? `Slab ${Math.abs(angle)}°` : `${angle}°`;
}

export default function WallAnglePicker({ angle, label, onChange }: Props) {
  const [custom, setCustom] = useState(!PRESETS.some((p) => p.label === label));

  return (
    <div className="space-y-3">
      <div className="grid grid-cols-3 gap-2">
        {PRESETS.map((preset) => {
          const selected = !custom && preset.label === label;
          return (
            <button
              key={preset.label}
              type="button"
              aria-pressed={selected}
              onClick={() => {
                setCustom(false);
                onChange(preset.angle, preset.label);
              }}
              className={`rounded-xl px-2 py-2.5 text-sm font-semibold transition-colors ${
                selected ? "bg-lime-400 text-slate-950" : "bg-slate-800 text-slate-200 active:bg-slate-700"
              }`}
            >
              {preset.label}
            </button>
          );
        })}
      </div>

      <button
        type="button"
        aria-pressed={custom}
        onClick={() => {
          setCustom(true);
          onChange(angle, customLabel(angle));
        }}
        className={`w-full rounded-xl px-3 py-2 text-sm font-semibold ${custom ? "bg-lime-400/15 text-lime-300 ring-1 ring-lime-400/60" : "bg-slate-800 text-slate-300"}`}
      >
        Custom angle (adjustable boards)
      </button>

      {custom && (
        <div className="rounded-xl bg-slate-900 p-3">
          <div className="mb-1 flex justify-between text-sm">
            <span className="text-slate-400">Angle past vertical</span>
            <span className="font-semibold text-lime-300">{customLabel(angle)}</span>
          </div>
          <input
            type="range"
            min={-30}
            max={70}
            step={5}
            value={angle}
            onChange={(event) => {
              const value = Number(event.target.value);
              onChange(value, customLabel(value));
            }}
            className="w-full accent-lime-400"
            aria-label="Wall angle in degrees"
          />
          <div className="flex justify-between text-[11px] text-slate-500">
            <span>Slab −30°</span><span>Vertical</span><span>70°</span>
          </div>
        </div>
      )}
      <p className="text-xs text-slate-400">
        On a Kilter, Tension or Moon board, use the angle the board is set to.
      </p>
    </div>
  );
}
