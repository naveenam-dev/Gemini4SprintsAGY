import type {
  AskResponse,
  CarePlanResponse,
  ExtractedDischarge,
  LanguageCode,
  SampleCase,
} from "./types";

async function handleJson<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let detail = `HTTP ${res.status}`;
    try {
      const data = await res.json();
      detail = data.detail || detail;
    } catch {
      // ignore non-json error body
    }
    throw new Error(detail);
  }
  return res.json() as Promise<T>;
}

export async function fetchSamples(): Promise<SampleCase[]> {
  const res = await fetch("/api/samples");
  const data = await handleJson<{ samples: SampleCase[] }>(res);
  return data.samples;
}

export async function extractDischarge(
  file: File | null,
  rawText: string
): Promise<ExtractedDischarge> {
  const form = new FormData();
  if (file) {
    form.append("file", file);
  }
  form.append("raw_text", rawText);

  const res = await fetch("/api/extract", {
    method: "POST",
    body: form,
  });
  return handleJson<ExtractedDischarge>(res);
}

export async function createCarePlan(
  extracted: ExtractedDischarge,
  language: LanguageCode,
  hospitalCity: string
): Promise<CarePlanResponse> {
  const res = await fetch("/api/care-plan", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      extracted,
      language,
      hospital_city: hospitalCity,
    }),
  });
  return handleJson<CarePlanResponse>(res);
}

export async function toggleChecklistItem(
  planId: string,
  itemId: string,
  checked: boolean
): Promise<CarePlanResponse> {
  const res = await fetch(`/api/plans/${planId}/checklist`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ item_id: itemId, checked }),
  });
  return handleJson<CarePlanResponse>(res);
}

export async function synthesizeTTS(
  text: string,
  language: LanguageCode
): Promise<Blob> {
  const res = await fetch("/api/tts", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ text, language }),
  });
  if (!res.ok) {
    throw new Error(`TTS failed (HTTP ${res.status})`);
  }
  return res.blob();
}

export async function askCareQuestion(
  planId: string,
  question: string,
  language: LanguageCode,
  previousInteractionId: string | null
): Promise<AskResponse> {
  const res = await fetch("/api/ask", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({
      plan_id: planId,
      question,
      language,
      previous_interaction_id: previousInteractionId,
    }),
  });
  return handleJson<AskResponse>(res);
}
