import type { Analysis, Coaching, HybridResult, Me, PoseResult } from "./types";

export const API_BASE = (import.meta.env.VITE_API_BASE_URL ?? "").replace(/\/$/, "");

const CODE_KEY = "climbcoach.invite";

// localStorage can throw (private mode, storage disabled), so every access is guarded.
export function getInviteCode(): string | null {
  try {
    return localStorage.getItem(CODE_KEY);
  } catch {
    return null;
  }
}

export function setInviteCode(code: string | null) {
  try {
    if (code) localStorage.setItem(CODE_KEY, code);
    else localStorage.removeItem(CODE_KEY);
  } catch {
    // Not persisted; the tester re-enters the code next time.
  }
}

export class ApiError extends Error {
  constructor(public status: number, message: string) {
    super(message);
  }
}

async function errorFrom(response: Response): Promise<ApiError> {
  let message = `Request failed (${response.status})`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") message = body.detail;
  } catch {
    // keep default message
  }
  return new ApiError(response.status, message);
}

async function request<T>(path: string, init: RequestInit = {}, code = getInviteCode()): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...init,
      headers: { ...(init.headers ?? {}), ...(code ? { Authorization: `Bearer ${code}` } : {}) },
    });
  } catch {
    throw new ApiError(0, "Can't reach the server. Check your connection.");
  }
  if (!response.ok) throw await errorFrom(response);
  return response.json() as Promise<T>;
}

export const api = {
  me: (code?: string) => request<Me>("/api/me", {}, code ?? getInviteCode()),
  listAnalyses: () => request<Analysis[]>("/api/analyses"),
  getAnalysis: (id: string) => request<Analysis>(`/api/analyses/${id}`),
  getPose: (id: string) => request<PoseResult>(`/api/analyses/${id}/pose`),
  getHybrid: (id: string) => request<HybridResult>(`/api/analyses/${id}/hybrid`),
  coaching: (id: string) =>
    request<{ coaching: Coaching; cached: boolean }>(`/api/analyses/${id}/coaching`, { method: "POST" }),
};

export function videoSrc(analysis: Analysis): string | null {
  return analysis.video_url ? `${API_BASE}${analysis.video_url}` : null;
}

/** Upload with progress (fetch can't report upload progress). */
export function uploadAnalysis(
  file: File,
  wallAngle: number,
  wallLabel: string,
  onProgress: (fraction: number) => void,
): Promise<Analysis> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    form.append("file", file, file.name || "climb.mp4");
    form.append("wall_angle_deg", String(wallAngle));
    form.append("wall_label", wallLabel);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/analyses`);
    const code = getInviteCode();
    if (code) xhr.setRequestHeader("Authorization", `Bearer ${code}`);

    xhr.upload.onprogress = (event) => {
      if (event.lengthComputable) onProgress(event.loaded / event.total);
    };
    xhr.onload = () => {
      let body: unknown = null;
      try {
        body = JSON.parse(xhr.responseText);
      } catch {
        // non-JSON error page
      }
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as Analysis);
      } else {
        const detail = (body as { detail?: unknown } | null)?.detail;
        reject(new ApiError(xhr.status, typeof detail === "string" ? detail : `Upload failed (${xhr.status})`));
      }
    };
    xhr.onerror = () => reject(new ApiError(0, "Upload failed. Check your connection and try again."));
    xhr.send(form);
  });
}
