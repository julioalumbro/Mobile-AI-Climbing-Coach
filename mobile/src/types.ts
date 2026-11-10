export type StageStatus = "pending" | "running" | "done" | "failed" | "skipped";
export type StageName = "normalize" | "pose" | "gemini" | "hybrid";

export interface Stage {
  status: StageStatus;
  error: string | null;
}

export interface Analysis {
  id: string;
  created_at: string;
  original_filename: string | null;
  wall_angle_deg: number;
  wall_label: string | null;
  wall_category: string;
  duration_seconds: number | null;
  status: "queued" | "processing" | "completed" | "failed" | "expired";
  error: string | null;
  stages: Record<StageName, Stage>;
  video_url: string | null;
}

export interface Me {
  name: string;
  analyses_today: number;
  daily_analysis_limit: number;
  ai_budget_available: boolean;
  max_video_seconds: number;
}

export interface OverlayFrame {
  t: number;
  /** 33 landmarks x (x, y, visibility), normalized 0-1, or null if no pose. */
  p: number[] | null;
}

export interface Overlay {
  fps: number;
  width: number;
  height: number;
  frames: OverlayFrame[];
}

export interface RuleFeedback {
  type: string;
  body_part: string;
  start_seconds: number;
  end_seconds: number;
  duration_seconds: number;
  observation: string;
  interpretation: string;
  recommendation: string;
  evidence_status: string;
  threshold_seconds: number;
  limitations: string[];
}

export interface ArmSummary {
  longest_duration: number;
  average_duration: number;
  total_duration: number;
}

export interface PoseResult {
  overlay: Overlay;
  feedback: RuleFeedback[];
  summary: {
    video: { fps: number; width: number; height: number; duration_seconds: number };
    wall: { angle_deg: number; category: string };
    tracking: { inference_frames: number; pose_detected_frames: number; pose_coverage: number | null };
    scale: { meters_per_pixel: number | null };
    left_arm: ArmSummary;
    right_arm: ArmSummary;
  };
}

export interface MetricEvaluation {
  metric: string;
  status: "supported" | "limited" | "insufficient";
  message: string;
}

export interface HybridItem {
  movement_type: string;
  movement_category: string;
  start_seconds: number;
  end_seconds: number;
  body_parts: string[];
  observation: string;
  gemini_confidence: "high" | "medium" | "low";
  evidence_status: "measurement_supported" | "partially_supported" | "insufficient_measurement_data";
  metric_evaluations: MetricEvaluation[];
  feedback: string;
}

export interface HybridResult {
  hybrid_feedback: HybridItem[];
}

export interface Coaching {
  /** One sentence: what the climber is doing wrong. */
  issue: string;
  /** One sentence: how to fix it. */
  fix: string;
}
