from __future__ import annotations

from typing import Literal, Optional
from pydantic import BaseModel, Field


LanguageCode = Literal["kn", "hi", "ta", "en"]
ConfidenceLevel = Literal["high", "medium", "low"]
AlertSeverity = Literal["critical", "warning", "info"]
SlotKey = Literal["morning", "afternoon", "night", "sos"]


class MedicationExtracted(BaseModel):
    id: str = Field(description="Short unique ID such as med_1, med_2")
    name: str = Field(description="Medication name, e.g., Tab. Metoprolol")
    strength: str = Field(description="Strength/dose per unit, e.g., 25 mg")
    frequency_code: str = Field(
        description="Dosing pattern such as 1-0-1, 0-1-0, 1-0-0, SOS, or OD"
    )
    meal_relation: str = Field(
        description="Timing with food, e.g., after breakfast, before food (AC), after food (PC), as needed (SOS)"
    )
    duration_days: Optional[int] = Field(
        default=None, description="Number of days prescribed if stated, else null"
    )
    route: str = Field(default="Oral", description="Route such as Oral or Sublingual (SL)")
    notes: str = Field(default="", description="Extra instructions or warnings")
    confidence: ConfidenceLevel = Field(
        default="high",
        description="Extraction confidence: low if handwriting/dose is ambiguous",
    )
    needs_pharmacist_review: bool = Field(
        default=False,
        description="True if handwriting is unclear or strength/frequency looks risky or ambiguous",
    )
    illegible_reason: str = Field(
        default="",
        description="Short reason if needs_pharmacist_review is true",
    )


class ExtractedDischarge(BaseModel):
    patient_summary: str = Field(
        description="Short anonymized patient/context summary (no real PII required)"
    )
    diagnosis: str = Field(description="Primary discharge diagnosis in plain English")
    discharge_date: str = Field(default="", description="Discharge date if present")
    follow_up_date: str = Field(default="", description="Follow-up visit date if present")
    follow_up_department: str = Field(
        default="", description="Follow-up doctor or department if present"
    )
    medications: list[MedicationExtracted] = Field(default_factory=list)
    raw_red_flags: list[str] = Field(
        default_factory=list,
        description="Warning symptoms mentioned in the discharge summary",
    )
    diet_activity_notes: list[str] = Field(
        default_factory=list,
        description="Diet, fluid, rest, or activity precautions",
    )
    overall_confidence: ConfidenceLevel = Field(default="high")
    pharmacist_review_required: bool = Field(default=False)
    reasoning_trace: list[str] = Field(default_factory=list)


class SafetyAlert(BaseModel):
    severity: AlertSeverity
    title: str
    detail: str
    action_required: str
    related_medications: list[str] = Field(default_factory=list)
    source: Literal["curated_rule", "gemini_thinking"] = "curated_rule"


class ScheduledDose(BaseModel):
    item_id: str
    medication_name: str
    strength: str
    dose_text: str = Field(description="Localized plain-language instruction, e.g., 1 tablet after breakfast")
    meal_note: str = Field(description="Localized food timing note")
    duration_label: str = Field(default="")
    caution: str = Field(default="")
    checked: bool = False


class ScheduleSlot(BaseModel):
    slot: SlotKey
    slot_title: str = Field(description="Localized slot title, e.g., ಬೆಳಿಗ್ಗೆ (Morning)")
    time_hint: str = Field(description="e.g., 8:00 AM")
    doses: list[ScheduledDose] = Field(default_factory=list)


class RedFlagBanner(BaseModel):
    headline: str = Field(description="Localized urgent escalation headline")
    symptoms: list[str] = Field(default_factory=list)
    emergency_number: str = "108"
    call_label: str = Field(description="Localized CTA, e.g., Call 108")
    maps_query: str = "nearest hospital emergency"
    maps_label: str = Field(description="Localized nearest hospital button text")


class CarePlanGenerated(BaseModel):
    summary_headline: str = Field(
        description="Warm, 1-2 sentence plain-language summary of recovery plan in the target language"
    )
    schedule: list[ScheduleSlot]
    safety_alerts_localized: list[SafetyAlert]
    red_flag_banner: RedFlagBanner
    follow_up_reminder: str
    diet_activity_tips: list[str]
    caregiver_script: str = Field(
        description="Natural, warm spoken care-plan script in the target language (max ~90 words) suitable for read-aloud TTS"
    )
    reasoning_trace: list[str] = Field(
        description="4-6 concise trace lines starting with [READ], [CHECK], [FLAG], [PLAN]"
    )


class CarePlanRequest(BaseModel):
    extracted: ExtractedDischarge
    language: LanguageCode = "kn"
    hospital_city: str = ""


class CarePlanResponse(BaseModel):
    plan_id: str
    language: LanguageCode
    language_name: str
    diagnosis: str
    follow_up_date: str
    follow_up_department: str
    pharmacist_review_required: bool
    summary_headline: str
    schedule: list[ScheduleSlot]
    safety_alerts: list[SafetyAlert]
    red_flag_banner: RedFlagBanner
    follow_up_reminder: str
    diet_activity_tips: list[str]
    caregiver_script: str
    reasoning_trace: list[str]
    thought_summary: str = ""
    disclaimer: str
    created_at: str


class ChecklistUpdateRequest(BaseModel):
    item_id: str
    checked: bool


class TTSRequest(BaseModel):
    text: str
    language: LanguageCode = "kn"


class AskRequest(BaseModel):
    plan_id: str
    question: str
    language: LanguageCode = "kn"
    previous_interaction_id: Optional[str] = None


class AskResponse(BaseModel):
    answer: str
    interaction_id: Optional[str] = None
    escalate_108: bool = False
