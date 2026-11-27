export type LanguageCode = "kn" | "hi" | "ta" | "en";
export type ConfidenceLevel = "high" | "medium" | "low";
export type AlertSeverity = "critical" | "warning" | "info";
export type SlotKey = "morning" | "afternoon" | "night" | "sos";

export interface SampleCase {
  id: string;
  title: string;
  badge: string;
  summary: string;
  raw_text: string;
}

export interface MedicationExtracted {
  id: string;
  name: string;
  strength: string;
  frequency_code: string;
  meal_relation: string;
  duration_days: number | null;
  route: string;
  notes: string;
  confidence: ConfidenceLevel;
  needs_pharmacist_review: boolean;
  illegible_reason: string;
  confirmed?: boolean;
}

export interface ExtractedDischarge {
  patient_summary: string;
  diagnosis: string;
  discharge_date: string;
  follow_up_date: string;
  follow_up_department: string;
  medications: MedicationExtracted[];
  raw_red_flags: string[];
  diet_activity_notes: string[];
  overall_confidence: ConfidenceLevel;
  pharmacist_review_required: boolean;
  reasoning_trace: string[];
}

export interface SafetyAlert {
  severity: AlertSeverity;
  title: string;
  detail: string;
  action_required: string;
  related_medications: string[];
  source: "curated_rule" | "gemini_thinking";
}

export interface ScheduledDose {
  item_id: string;
  medication_name: string;
  strength: string;
  dose_text: string;
  meal_note: string;
  duration_label: string;
  caution: string;
  checked: boolean;
}

export interface ScheduleSlot {
  slot: SlotKey;
  slot_title: string;
  time_hint: string;
  doses: ScheduledDose[];
}

export interface RedFlagBanner {
  headline: string;
  symptoms: string[];
  emergency_number: string;
  call_label: string;
  maps_query: string;
  maps_label: string;
}

export interface CarePlanResponse {
  plan_id: string;
  language: LanguageCode;
  language_name: string;
  diagnosis: string;
  follow_up_date: string;
  follow_up_department: string;
  pharmacist_review_required: boolean;
  summary_headline: string;
  schedule: ScheduleSlot[];
  safety_alerts: SafetyAlert[];
  red_flag_banner: RedFlagBanner;
  follow_up_reminder: string;
  diet_activity_tips: string[];
  caregiver_script: string;
  reasoning_trace: string[];
  thought_summary: string;
  disclaimer: string;
  created_at: string;
}

export interface AskResponse {
  answer: string;
  interaction_id: string | null;
  escalate_108: boolean;
}
