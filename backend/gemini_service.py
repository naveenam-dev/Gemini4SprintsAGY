from __future__ import annotations

import base64
import json
import os
from typing import Optional

from google import genai
from google.genai import types

from .safety_rules import run_curated_safety_checks
from .schemas import (
    CarePlanGenerated,
    ExtractedDischarge,
    LanguageCode,
    SafetyAlert,
)

LANGUAGE_NAMES: dict[LanguageCode, str] = {
    "kn": "Kannada (ಕನ್ನಡ)",
    "hi": "Hindi (हिन्दी)",
    "ta": "Tamil (தமிழ்)",
    "en": "English",
}

CLINICAL_DISCLAIMER = (
    "Clinical safety: Discharge Dost is a comprehension aid, never a medical diagnosis. "
    "Always verify unclear handwriting or new symptoms with a licensed pharmacist or doctor. "
    "For emergencies, call 108 immediately."
)

TEXT_MODEL = os.getenv("GEMINI_MODEL", "gemini-4-hydrogen")
TTS_MODEL = os.getenv("GEMINI_TTS_MODEL", "gemini-3.8-flash-tts")
LIVE_MODEL = os.getenv("GEMINI_LIVE_MODEL", "gemini-3.8-live")


def build_live_system_instruction(plan_context: dict, language: LanguageCode) -> str:
    target_lang = LANGUAGE_NAMES[language]
    return (
        f"You are Discharge Dost, a warm, calm clinical comprehension voice assistant speaking simple {target_lang}.\n"
        "You are helping a patient's family understand their hospital discharge care plan over live voice.\n"
        "Strict rules:\n"
        "1. Answer ONLY from the confirmed discharge plan below. Never invent new prescriptions or dosages.\n"
        "2. Keep spoken replies concise (2-3 short, clear sentences) so they are easy to follow on audio.\n"
        "3. If they ask about painkillers while on blood thinners (e.g., Ecosprin/Aspirin), remind them to ask their pharmacist first.\n"
        "4. If they mention chest pain, trouble breathing, fainting, or heavy bleeding, immediately tell them to call 108 and go to the nearest emergency hospital.\n\n"
        f"Confirmed Care Plan JSON:\n{json.dumps(plan_context, ensure_ascii=False)}"
    )


def create_live_config(plan_context: dict, language: LanguageCode) -> types.LiveConnectConfig:
    return types.LiveConnectConfig(
        response_modalities=[types.Modality.AUDIO],
        input_audio_transcription=types.AudioTranscriptionConfig(),
        output_audio_transcription=types.AudioTranscriptionConfig(),
        speech_config=types.SpeechConfig(
            voice_config=types.VoiceConfig(
                prebuilt_voice_config=types.PrebuiltVoiceConfig(voice_name="Kore")
            )
        ),
        system_instruction=types.Content(
            parts=[types.Part(text=build_live_system_instruction(plan_context, language))]
        ),
    )


def _get_client(api_version: Optional[str] = None) -> genai.Client:
    api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError(
            "GEMINI_API_KEY is not configured. Set it in .env or Cloud Run environment variables."
        )
    if api_version:
        return genai.Client(api_key=api_key, http_options={"api_version": api_version})
    return genai.Client(api_key=api_key)


def _extract_thought_summary(interaction) -> str:
    summaries: list[str] = []
    for step in getattr(interaction, "steps", None) or []:
        if getattr(step, "type", None) == "thought":
            summary = getattr(step, "summary", None)
            if isinstance(summary, str) and summary.strip():
                summaries.append(summary.strip())
            elif isinstance(summary, list):
                for item in summary:
                    text = getattr(item, "text", None) or (item.get("text") if isinstance(item, dict) else None)
                    if text:
                        summaries.append(str(text).strip())
    return "\n".join(summaries).strip()


def extract_discharge_summary(
    *,
    image_bytes: Optional[bytes] = None,
    mime_type: Optional[str] = None,
    raw_text: str = "",
) -> ExtractedDischarge:
    """Step 1: Multimodal Vision + Structured JSON extraction from paper/photo or text."""
    client = _get_client()

    prompt = (
        "You are Discharge Dost's clinical extraction agent. Read the provided hospital discharge "
        "summary (image, PDF, or text) carefully.\n"
        "Rules:\n"
        "1. Parse Indian prescription shorthand accurately: '1-0-1' = Morning & Night, "
        "'0-1-0' = Afternoon, '1-1-1' = Morning/Afternoon/Night, 'AC' = before food (Ante Cibum), "
        "'PC' = after food (Post Cibum), 'OD' = once daily, 'BD' = twice daily, 'SOS' = as needed, "
        "'SL' = under the tongue (sublingual).\n"
        "2. NEVER guess an illegible strength (e.g., 5 mg vs 50 mg) silently—if anything is faint, smudged, "
        "cut off, or ambiguous, set confidence='low' and needs_pharmacist_review=true with an illegible_reason.\n"
        "3. Omit or anonymize personal identifiers (patient name/phone) in patient_summary.\n"
        "4. Populate reasoning_trace with 2-3 concise lines starting with '[READ]' or '[PARSE]' summarizing "
        "what was extracted and any uncertainty."
    )

    content_parts: list[dict] = [{"type": "text", "text": prompt}]
    if raw_text.strip():
        content_parts.append({"type": "text", "text": f"Discharge summary text:\n{raw_text.strip()}"})

    if image_bytes:
        b64_data = base64.b64encode(image_bytes).decode("utf-8")
        effective_mime = mime_type or "image/jpeg"
        if effective_mime == "application/pdf":
            content_parts.append({"type": "document", "data": b64_data, "mime_type": effective_mime})
        else:
            content_parts.append({"type": "image", "data": b64_data, "mime_type": effective_mime})

    interaction = client.interactions.create(
        model=TEXT_MODEL,
        input=content_parts,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": ExtractedDischarge.model_json_schema(),
        },
        generation_config={
            "thinking_level": "low",
            "thinking_summaries": "auto",
            "temperature": 0.1,
        },
    )

    parsed = ExtractedDischarge.model_validate_json(interaction.output_text or "{}")
    if any(m.needs_pharmacist_review or m.confidence == "low" for m in parsed.medications):
        parsed.pharmacist_review_required = True
    return parsed


def build_care_plan(
    confirmed: ExtractedDischarge,
    language: LanguageCode = "kn",
    hospital_city: str = "",
) -> tuple[CarePlanGenerated, list[SafetyAlert], str]:
    """Step 3 & 4: Curated Safety Rules + Gemini 4 Thinking + Vernacular Care Plan."""
    curated_alerts, curated_trace = run_curated_safety_checks(confirmed)
    target_lang_name = LANGUAGE_NAMES[language]
    client = _get_client()

    payload = {
        "confirmed_discharge": confirmed.model_dump(),
        "curated_safety_alerts": [a.model_dump() for a in curated_alerts],
        "target_language": target_lang_name,
        "language_code": language,
        "hospital_city": hospital_city.strip() or "India",
    }

    prompt = (
        f"You are Discharge Dost's clinical safety reasoner and vernacular care-plan agent.\n"
        f"Target language: {target_lang_name} (code: {language}).\n\n"
        "Tasks:\n"
        "1. Review the confirmed medications and curated safety alerts. Use your clinical reasoning to check "
        "for any additional drug interactions, duplicate therapies, timing conflicts (e.g., before vs after meal, "
        "SOS sublingual nitrate instructions), or unsafe gaps. Keep it practical and non-diagnostic.\n"
        "2. Build a clear daily schedule across slots in this exact order when applicable: "
        "'morning', 'afternoon', 'night', 'sos'. Always include at least the slots that have medicines.\n"
        "   - Translate slot_title into the target language (e.g., for Kannada: 'ಬೆಳಿಗ್ಗೆ' with English hint if helpful, "
        "for Hindi: 'सुबह', for Tamil: 'காலை').\n"
        f"   - Keep the medicine brand/generic name clearly readable (e.g., 'Metoprolol 25 mg') so families match the pill strip, "
        f"and write `dose_text`, `meal_note`, `duration_label`, and `caution` in simple, everyday spoken {target_lang_name} "
        "(6th-grade reading level, warm and reassuring).\n"
        f"3. Localize all safety alerts into `safety_alerts_localized` (preserve all curated alerts + add any extra reasoning alerts).\n"
        f"4. Build `red_flag_banner` in {target_lang_name}: urgent symptoms like chest pain, shortness of breath, fainting, "
        "or heavy bleeding -> Call 108 immediately + nearest hospital Maps link (`maps_query`: 'nearest emergency hospital "
        f"{hospital_city.strip()}').\n"
        f"5. Write `caregiver_script`: a warm, natural 60-90 word spoken summary in {target_lang_name} covering morning/afternoon/night "
        "medicines, key painkiller/food caution, and when to call 108—ready for Gemini TTS read-aloud.\n"
        "6. Populate `reasoning_trace` with 4-6 short status lines prefixed by [READ], [CHECK], [FLAG], [PLAN] suitable for a live agent trace UI.\n\n"
        f"Input JSON:\n{json.dumps(payload, ensure_ascii=False)}"
    )

    interaction = client.interactions.create(
        model=TEXT_MODEL,
        input=prompt,
        response_format={
            "type": "text",
            "mime_type": "application/json",
            "schema": CarePlanGenerated.model_json_schema(),
        },
        generation_config={
            "thinking_level": "medium",
            "thinking_summaries": "auto",
            "temperature": 0.2,
        },
    )

    generated = CarePlanGenerated.model_validate_json(interaction.output_text or "{}")
    thought_summary = _extract_thought_summary(interaction)

    # Ensure curated trace lines are preserved if the model summarized too briefly
    combined_trace = list(generated.reasoning_trace)
    if not combined_trace:
        combined_trace = confirmed.reasoning_trace + curated_trace

    return generated, curated_alerts, thought_summary


def synthesize_tts_wav(text: str, language: LanguageCode = "kn") -> bytes:
    """Generate natural read-aloud WAV audio using Gemini 3.8 Flash TTS."""
    client = _get_client(api_version="v1beta")
    style_map = {
        "kn": "warm, calm, clear Indian caregiver reading Kannada slowly and reassuringly",
        "hi": "warm, calm, clear Indian caregiver reading Hindi slowly and reassuringly",
        "ta": "warm, calm, clear Indian caregiver reading Tamil slowly and reassuringly",
        "en": "warm, calm, clear Indian caregiver reading English slowly and reassuringly",
    }

    interaction = client.interactions.create(
        model=TTS_MODEL,
        input=[
            {
                "type": "user_input",
                "content": [
                    {
                        "type": "text",
                        "text": text.strip()[:1800],
                        "annotations": [
                            {
                                "type": "speech_metadata",
                                "style": style_map.get(language, style_map["en"]),
                            }
                        ],
                    }
                ],
            }
        ],
        response_format={"type": "audio"},
        generation_config={
            "speech_config": [{"voice": "Kore"}],
        },
    )

    if not interaction.output_audio or not interaction.output_audio.data:
        raise RuntimeError("TTS model did not return audio data.")
    return base64.b64decode(interaction.output_audio.data)


def answer_care_question(
    *,
    plan_context: dict,
    question: str,
    language: LanguageCode,
    previous_interaction_id: Optional[str] = None,
) -> tuple[str, Optional[str], bool]:
    """Caregiver Q&A grounded strictly in the verified discharge care plan."""
    client = _get_client()
    target_lang = LANGUAGE_NAMES[language]

    red_flag_terms = (
        "chest pain",
        "breath",
        "breathing",
        "faint",
        "unconscious",
        "bleeding",
        "blood",
        "collapse",
        "dizzy",
        "ಎದೆ ನೋವು",
        "सीने में दर्द",
        "நெஞ்சு வலி",
    )
    escalate = any(term in question.lower() for term in red_flag_terms)

    if previous_interaction_id:
        user_input = (
            f"User question (answer in simple {target_lang}, max 4 short sentences, "
            f"remind them to call 108 if emergency symptoms occur, never invent new prescriptions): {question}"
        )
        interaction = client.interactions.create(
            model=TEXT_MODEL,
            input=user_input,
            previous_interaction_id=previous_interaction_id,
            generation_config={"thinking_level": "low", "temperature": 0.2},
        )
    else:
        prompt = (
            f"You are Discharge Dost, a safe caregiver assistant speaking simple {target_lang}.\n"
            "Answer the family member's question ONLY using this confirmed discharge care plan.\n"
            "Rules: Never diagnose or add unprescribed medicines. If they ask about painkillers on blood thinners, "
            "tell them to check with a pharmacist first. If they describe chest pain, breathlessness, fainting, or bleeding, "
            "tell them to call 108 immediately and go to the nearest emergency hospital.\n\n"
            f"Care plan context:\n{json.dumps(plan_context, ensure_ascii=False)}\n\n"
            f"Question: {question}"
        )
        interaction = client.interactions.create(
            model=TEXT_MODEL,
            input=prompt,
            generation_config={"thinking_level": "low", "temperature": 0.2},
        )

    return (interaction.output_text or "").strip(), getattr(interaction, "id", None), escalate
