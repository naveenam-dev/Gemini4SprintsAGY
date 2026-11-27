import { useEffect, useRef, useState } from "react";
import {
  AlertTriangle,
  Camera,
  Check,
  CheckCircle2,
  FileText,
  HeartPulse,
  Loader2,
  MapPin,
  MessageCircle,
  PhoneCall,
  Plus,
  ShieldAlert,
  Sparkles,
  Trash2,
  Volume2,
} from "lucide-react";
import {
  askCareQuestion,
  createCarePlan,
  extractDischarge,
  fetchSamples,
  synthesizeTTS,
  toggleChecklistItem,
} from "./api";
import LiveVoicePanel from "./LiveVoicePanel";
import type {
  CarePlanResponse,
  ExtractedDischarge,
  LanguageCode,
  MedicationExtracted,
  SampleCase,
} from "./types";

const LANGUAGES: { code: LanguageCode; native: string; label: string; bcp47: string }[] = [
  { code: "kn", native: "ಕನ್ನಡ", label: "Kannada", bcp47: "kn-IN" },
  { code: "hi", native: "हिन्दी", label: "Hindi", bcp47: "hi-IN" },
  { code: "ta", native: "தமிழ்", label: "Tamil", bcp47: "ta-IN" },
  { code: "en", native: "English", label: "English", bcp47: "en-IN" },
];

function TraceLine({ line }: { line: string }) {
  const upper = line.trim();
  let cls = "";
  if (upper.startsWith("[READ]") || upper.startsWith("[PARSE]")) cls = "trace-tag-read";
  else if (upper.startsWith("[CHECK]")) cls = "trace-tag-check";
  else if (upper.startsWith("[FLAG]")) cls = "trace-tag-flag";
  else if (upper.startsWith("[PLAN]")) cls = "trace-tag-plan";

  const splitIdx = line.indexOf("]");
  if (splitIdx > 0 && cls) {
    return (
      <div className="trace-line">
        <span className={cls}>{line.slice(0, splitIdx + 1)}</span>
        {line.slice(splitIdx + 1)}
      </div>
    );
  }
  return <div className="trace-line">{line}</div>;
}

export default function App() {
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [samples, setSamples] = useState<SampleCase[]>([]);
  const [language, setLanguage] = useState<LanguageCode>("kn");
  const [hospitalCity, setHospitalCity] = useState("Bengaluru");

  // Step 1 state
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [previewUrl, setPreviewUrl] = useState<string | null>(null);
  const [rawText, setRawText] = useState("");
  const [extracting, setExtracting] = useState(false);

  // Step 2 state
  const [extracted, setExtracted] = useState<ExtractedDischarge | null>(null);
  const [generatingPlan, setGeneratingPlan] = useState(false);

  // Step 3 state
  const [carePlan, setCarePlan] = useState<CarePlanResponse | null>(null);
  const [ttsLoading, setTtsLoading] = useState(false);
  const [audioUrl, setAudioUrl] = useState<string | null>(null);
  const audioRef = useRef<HTMLAudioElement | null>(null);

  // Q&A state
  const [question, setQuestion] = useState("");
  const [qaMessages, setQaMessages] = useState<
    { role: "user" | "assistant"; text: string; escalate?: boolean }[]
  >([]);
  const [interactionId, setInteractionId] = useState<string | null>(null);
  const [asking, setAsking] = useState(false);

  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  useEffect(() => {
    fetchSamples()
      .then(setSamples)
      .catch(() => {
        // non-blocking
      });
  }, []);

  useEffect(() => {
    return () => {
      if (previewUrl) URL.revokeObjectURL(previewUrl);
      if (audioUrl) URL.revokeObjectURL(audioUrl);
    };
  }, [previewUrl, audioUrl]);

  const handleFileChange = (file: File | null) => {
    if (previewUrl) URL.revokeObjectURL(previewUrl);
    setSelectedFile(file);
    if (file && file.type.startsWith("image/")) {
      setPreviewUrl(URL.createObjectURL(file));
    } else {
      setPreviewUrl(null);
    }
  };

  const loadSampleImage = async (filename: string) => {
    setErrorMsg(null);
    try {
      const res = await fetch(`/samples/${filename}`);
      if (!res.ok) throw new Error("Sample photo not found");
      const blob = await res.blob();
      const file = new File([blob], filename, { type: "image/png" });
      setRawText("");
      handleFileChange(file);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Could not load sample photo");
    }
  };

  const handleExtract = async () => {
    setErrorMsg(null);
    setExtracting(true);
    try {
      const result = await extractDischarge(selectedFile, rawText);
      const withConfirm = {
        ...result,
        medications: result.medications.map((m) => ({
          ...m,
          confirmed: !m.needs_pharmacist_review && m.confidence !== "low",
        })),
      };
      setExtracted(withConfirm);
      setStep(2);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Extraction failed");
    } finally {
      setExtracting(false);
    }
  };

  const updateMedication = (
    idx: number,
    patch: Partial<MedicationExtracted>
  ) => {
    if (!extracted) return;
    const next = [...extracted.medications];
    next[idx] = { ...next[idx], ...patch };
    setExtracted({ ...extracted, medications: next });
  };

  const addBlankMedication = () => {
    if (!extracted) return;
    const id = `med_${extracted.medications.length + 1}`;
    setExtracted({
      ...extracted,
      medications: [
        ...extracted.medications,
        {
          id,
          name: "",
          strength: "",
          frequency_code: "1-0-1",
          meal_relation: "after meals",
          duration_days: 7,
          route: "Oral",
          notes: "",
          confidence: "high",
          needs_pharmacist_review: false,
          illegible_reason: "",
          confirmed: true,
        },
      ],
    });
  };

  const removeMedication = (idx: number) => {
    if (!extracted) return;
    const next = extracted.medications.filter((_, i) => i !== idx);
    setExtracted({ ...extracted, medications: next });
  };

  const handleGenerateCarePlan = async () => {
    if (!extracted) return;
    setErrorMsg(null);
    setGeneratingPlan(true);
    setAudioUrl(null);
    setQaMessages([]);
    setInteractionId(null);
    try {
      const cleaned: ExtractedDischarge = {
        ...extracted,
        medications: extracted.medications.map(({ confirmed: _c, ...rest }) => rest),
      };
      const plan = await createCarePlan(cleaned, language, hospitalCity);
      setCarePlan(plan);
      setStep(3);
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Could not generate care plan");
    } finally {
      setGeneratingPlan(false);
    }
  };

  const handleListen = async (textToRead: string, langCode: LanguageCode) => {
    setErrorMsg(null);
    setTtsLoading(true);
    try {
      const blob = await synthesizeTTS(textToRead, langCode);
      if (audioUrl) URL.revokeObjectURL(audioUrl);
      const url = URL.createObjectURL(blob);
      setAudioUrl(url);
      setTimeout(() => {
        audioRef.current?.play().catch(() => {});
      }, 60);
    } catch {
      // Graceful browser speech fallback
      if ("speechSynthesis" in window) {
        window.speechSynthesis.cancel();
        const utter = new SpeechSynthesisUtterance(textToRead);
        utter.lang = LANGUAGES.find((l) => l.code === langCode)?.bcp47 || "en-IN";
        window.speechSynthesis.speak(utter);
      } else {
        setErrorMsg("Audio playback unavailable right now.");
      }
    } finally {
      setTtsLoading(false);
    }
  };

  const handleToggleDose = async (itemId: string, currentChecked: boolean) => {
    if (!carePlan) return;
    try {
      const updated = await toggleChecklistItem(carePlan.plan_id, itemId, !currentChecked);
      setCarePlan(updated);
    } catch {
      // optimistic fallback ignored
    }
  };

  const handleAsk = async () => {
    if (!carePlan || !question.trim()) return;
    const q = question.trim();
    setQuestion("");
    setQaMessages((prev) => [...prev, { role: "user", text: q }]);
    setAsking(true);
    try {
      const resp = await askCareQuestion(carePlan.plan_id, q, carePlan.language, interactionId);
      setInteractionId(resp.interaction_id);
      setQaMessages((prev) => [
        ...prev,
        { role: "assistant", text: resp.answer, escalate: resp.escalate_108 },
      ]);
    } catch (err) {
      setQaMessages((prev) => [
        ...prev,
        {
          role: "assistant",
          text: err instanceof Error ? err.message : "Unable to answer right now.",
        },
      ]);
    } finally {
      setAsking(false);
    }
  };

  const allConfirmed =
    extracted &&
    extracted.medications.length > 0 &&
    extracted.medications.every((m) => m.confirmed && m.name.trim().length > 0);

  return (
    <div className="app-shell">
      <header className="topbar">
        <div className="brand">
          <div className="brand-mark">
            <HeartPulse size={24} />
          </div>
          <div>
            <h1>Discharge Dost</h1>
            <p>Safe, vernacular daily care plans from English hospital discharge summaries</p>
          </div>
        </div>
        <div className="pill-row">
          <span className="badge">
            <Sparkles size={14} /> Gemini 4 Vision + Thinking
          </span>
          <span className="badge">
            <Volume2 size={14} /> Gemini 3.8 TTS
          </span>
          <span className="badge badge-dark">Cloud Run</span>
        </div>
      </header>

      <nav className="stepper" aria-label="Workflow steps">
        <button
          type="button"
          className={`step-pill ${step === 1 ? "active" : step > 1 ? "done" : ""}`}
          onClick={() => setStep(1)}
        >
          <span className="step-num">1</span>
          <span>Snap &amp; Extract</span>
        </button>
        <button
          type="button"
          className={`step-pill ${step === 2 ? "active" : step > 2 ? "done" : ""}`}
          onClick={() => extracted && setStep(2)}
          disabled={!extracted}
        >
          <span className="step-num">2</span>
          <span>Human Confirm</span>
        </button>
        <button
          type="button"
          className={`step-pill ${step === 3 ? "active" : ""}`}
          onClick={() => carePlan && setStep(3)}
          disabled={!carePlan}
        >
          <span className="step-num">3</span>
          <span>Vernacular Plan &amp; Voice</span>
        </button>
      </nav>

      {errorMsg && (
        <div className="alert-box critical" role="alert">
          <strong>Error:</strong> {errorMsg}
        </div>
      )}

      {/* STEP 1: UPLOAD / PASTE / LANGUAGE */}
      {step === 1 && (
        <div className="grid-2">
          <section className="card">
            <h2 className="section-title">
              <Camera size={19} color="#0b6e63" /> 01 · Upload Discharge Summary or Paste Text
            </h2>
            <p className="muted">
              Supports printed or handwritten English prescriptions (`1-0-1`, `AC`, `SOS`), photos, and PDFs.
            </p>

            <div className="lang-grid" role="group" aria-label="Care plan language">
              {LANGUAGES.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  className={`lang-btn ${language === l.code ? "selected" : ""}`}
                  onClick={() => setLanguage(l.code)}
                >
                  {l.native}
                  <span>{l.label}</span>
                </button>
              ))}
            </div>

            <label className="upload-box" style={{ display: "block" }}>
              <input
                type="file"
                accept="image/*,application/pdf"
                capture="environment"
                style={{ display: "none" }}
                onChange={(e) => handleFileChange(e.target.files?.[0] || null)}
              />
              <Camera size={26} color="#0b6e63" />
              <div style={{ fontWeight: 600, marginTop: 6 }}>
                {selectedFile
                  ? `Selected: ${selectedFile.name}`
                  : "Tap to snap photo or upload discharge summary (JPG/PNG/PDF)"}
              </div>
              <div className="muted" style={{ fontSize: "0.8rem" }}>
                Processed by Gemini 4 Vision · Never used as medical diagnosis
              </div>
            </label>

            {previewUrl && (
              <div style={{ marginBottom: 14 }}>
                <img
                  src={previewUrl}
                  alt="Uploaded discharge preview"
                  style={{
                    maxHeight: 210,
                    width: "100%",
                    objectFit: "contain",
                    borderRadius: 12,
                    border: "1px solid var(--border)",
                  }}
                />
              </div>
            )}

            <label style={{ display: "block", fontWeight: 600, fontSize: "0.86rem", marginBottom: 6 }}>
              Or paste / edit discharge summary text:
            </label>
            <textarea
              className="textarea"
              placeholder="Paste discharge medications here (e.g. Tab. Metoprolol 25 mg 1-0-1 x 30d, Tab. Ecosprin 75 mg 0-1-0 AC...)"
              value={rawText}
              onChange={(e) => setRawText(e.target.value)}
            />

            <div style={{ display: "flex", gap: 10, marginTop: 14, flexWrap: "wrap", alignItems: "center" }}>
              <input
                className="input"
                style={{ maxWidth: 200 }}
                value={hospitalCity}
                onChange={(e) => setHospitalCity(e.target.value)}
                placeholder="City for nearest ER"
                aria-label="City for nearest hospital"
              />
              <button
                type="button"
                className="btn btn-primary"
                disabled={extracting || (!selectedFile && !rawText.trim())}
                onClick={handleExtract}
              >
                {extracting ? (
                  <>
                    <Loader2 size={17} className="spinner" /> Reading with Gemini 4 Vision...
                  </>
                ) : (
                  <>
                    <FileText size={17} /> Extract Medicines
                  </>
                )}
              </button>
            </div>
          </section>

          <aside className="card">
            <h2 className="section-title">
              <Sparkles size={19} color="#0b6e63" /> Try Synthetic Clinical Samples
            </h2>
            <p className="muted" style={{ marginBottom: 10 }}>
              Load a synthetic prescription <strong>photo</strong> (Gemini 4 Vision) or text note:
            </p>
            <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginBottom: 12 }}>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ fontSize: "0.8rem", padding: "8px 12px" }}
                onClick={() => loadSampleImage("cardiac-discharge.png")}
              >
                <Camera size={15} /> Cardiac Rx Photo
              </button>
              <button
                type="button"
                className="btn btn-secondary"
                style={{ fontSize: "0.8rem", padding: "8px 12px" }}
                onClick={() => loadSampleImage("handwritten-smudge.png")}
              >
                <Camera size={15} /> Smudged Dose Photo
              </button>
            </div>
            {samples.map((s) => (
              <button
                key={s.id}
                type="button"
                className="sample-card"
                onClick={() => {
                  handleFileChange(null);
                  setRawText(s.raw_text);
                }}
              >
                <div style={{ display: "flex", justifyContent: "space-between", gap: 8, marginBottom: 4 }}>
                  <strong style={{ fontSize: "0.92rem" }}>{s.title}</strong>
                  <span className="badge" style={{ fontSize: "0.7rem", padding: "3px 8px" }}>
                    {s.badge}
                  </span>
                </div>
                <div className="muted" style={{ fontSize: "0.82rem" }}>
                  {s.summary}
                </div>
              </button>
            ))}

            <div className="trace-card" style={{ marginTop: 14 }}>
              <div style={{ color: "#94a3b8", fontSize: "0.72rem", marginBottom: 6 }}>
                HOW DISCHARGE DOST PROTECTS FAMILIES
              </div>
              <div className="trace-line">
                <span className="trace-tag-read">[01 VISION]</span> Reads 1-0-1, AC, PC, SOS &amp; flags unclear handwriting
              </div>
              <div className="trace-line">
                <span className="trace-tag-check">[02 CONFIRM]</span> Human checks 5 mg vs 50 mg before care plan runs
              </div>
              <div className="trace-line">
                <span className="trace-tag-flag">[03 SAFETY]</span> Curated drug interactions + Gemini 4 Thinking
              </div>
              <div className="trace-line">
                <span className="trace-tag-plan">[04 VOICE]</span> Kannada, Hindi, Tamil &amp; English + 108 escalation
              </div>
            </div>
          </aside>
        </div>
      )}

      {/* STEP 2: HUMAN-IN-THE-LOOP CONFIRM */}
      {step === 2 && extracted && (
        <section className="card">
          <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 12, marginBottom: 14 }}>
            <div>
              <h2 className="section-title">
                <CheckCircle2 size={20} color="#0b6e63" /> 02 · Confirm Every Extracted Medicine
              </h2>
              <p className="muted" style={{ margin: 0 }}>
                Diagnosis: <strong>{extracted.diagnosis}</strong>
                {extracted.follow_up_date ? ` · Follow-up: ${extracted.follow_up_date}` : ""}
              </p>
            </div>
            <div className="pill-row">
              {LANGUAGES.map((l) => (
                <button
                  key={l.code}
                  type="button"
                  className={`lang-btn ${language === l.code ? "selected" : ""}`}
                  style={{ padding: "6px 12px" }}
                  onClick={() => setLanguage(l.code)}
                >
                  {l.native}
                </button>
              ))}
            </div>
          </div>

          {extracted.pharmacist_review_required && (
            <div className="alert-box warning">
              <strong>
                <AlertTriangle size={16} style={{ verticalAlign: "text-bottom" }} /> Low-Confidence / Ambiguous Handwriting Detected:
              </strong>{" "}
              Please verify highlighted strengths (e.g. 5 mg vs 50 mg) against the physical pill strip or ask your pharmacist before confirming.
            </div>
          )}

          {extracted.medications.map((med, idx) => {
            const isFlagged = med.needs_pharmacist_review || med.confidence === "low";
            return (
              <div
                key={med.id + idx}
                className={`med-edit-card ${med.confirmed ? "confirmed" : isFlagged ? "flagged" : ""}`}
              >
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 8, flexWrap: "wrap" }}>
                  <div style={{ display: "flex", alignItems: "center", gap: 8 }}>
                    <span className="badge">#{idx + 1}</span>
                    {isFlagged && !med.confirmed && (
                      <span className="badge" style={{ background: "#fef3c7", color: "#92400e", borderColor: "#fcd34d" }}>
                        Needs review: {med.illegible_reason || "low confidence"}
                      </span>
                    )}
                  </div>
                  <div style={{ display: "flex", gap: 8 }}>
                    <button
                      type="button"
                      className={`btn ${med.confirmed ? "btn-primary" : "btn-secondary"}`}
                      style={{ padding: "7px 12px", fontSize: "0.82rem" }}
                      onClick={() =>
                        updateMedication(idx, {
                          confirmed: !med.confirmed,
                          needs_pharmacist_review: false,
                        })
                      }
                    >
                      <Check size={15} /> {med.confirmed ? "Confirmed" : "Tick to Confirm"}
                    </button>
                    <button
                      type="button"
                      className="btn btn-secondary"
                      style={{ padding: "7px 10px" }}
                      onClick={() => removeMedication(idx)}
                      aria-label="Remove medicine"
                    >
                      <Trash2 size={15} />
                    </button>
                  </div>
                </div>

                <div className="med-grid">
                  <div>
                    <label className="muted" style={{ fontSize: "0.75rem" }}>Medicine Name</label>
                    <input
                      className="input"
                      value={med.name}
                      onChange={(e) => updateMedication(idx, { name: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="muted" style={{ fontSize: "0.75rem" }}>Strength</label>
                    <input
                      className="input"
                      value={med.strength}
                      onChange={(e) => updateMedication(idx, { strength: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="muted" style={{ fontSize: "0.75rem" }}>Pattern</label>
                    <input
                      className="input"
                      value={med.frequency_code}
                      onChange={(e) => updateMedication(idx, { frequency_code: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="muted" style={{ fontSize: "0.75rem" }}>Food / Timing</label>
                    <input
                      className="input"
                      value={med.meal_relation}
                      onChange={(e) => updateMedication(idx, { meal_relation: e.target.value })}
                    />
                  </div>
                  <div>
                    <label className="muted" style={{ fontSize: "0.75rem" }}>Days</label>
                    <input
                      className="input"
                      type="number"
                      value={med.duration_days ?? ""}
                      onChange={(e) =>
                        updateMedication(idx, {
                          duration_days: e.target.value ? Number(e.target.value) : null,
                        })
                      }
                    />
                  </div>
                </div>
              </div>
            );
          })}

          <div style={{ display: "flex", justifyContent: "space-between", flexWrap: "wrap", gap: 12, marginTop: 16 }}>
            <button type="button" className="btn btn-secondary" onClick={addBlankMedication}>
              <Plus size={16} /> Add Missing Medicine
            </button>

            <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
              <button type="button" className="btn btn-secondary" onClick={() => setStep(1)}>
                Back
              </button>
              <button
                type="button"
                className="btn btn-primary"
                disabled={!allConfirmed || generatingPlan}
                onClick={handleGenerateCarePlan}
              >
                {generatingPlan ? (
                  <>
                    <Loader2 size={17} className="spinner" /> Running Safety Check &amp; Translating...
                  </>
                ) : (
                  <>
                    <ShieldAlert size={17} /> Run Safety Check &amp; Build Care Plan
                  </>
                )}
              </button>
            </div>
          </div>
          {!allConfirmed && (
            <p className="muted" style={{ marginTop: 10, fontSize: "0.82rem" }}>
              Please confirm all medicine rows above before generating the vernacular care plan.
            </p>
          )}
        </section>
      )}

      {/* STEP 3: VERNACULAR CARE PLAN + VOICE + TRACE */}
      {step === 3 && carePlan && (
        <div>
          {/* Red-Flag 108 Escalation Banner */}
          <div className="red-flag-banner">
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 12 }}>
              <div>
                <div style={{ fontWeight: 700, fontSize: "1.12rem", marginBottom: 4 }}>
                  {carePlan.red_flag_banner.headline}
                </div>
                <div style={{ fontSize: "0.88rem", opacity: 0.92 }}>
                  {carePlan.red_flag_banner.symptoms.join(" · ")}
                </div>
              </div>
              <div style={{ display: "flex", gap: 10, flexWrap: "wrap" }}>
                <a
                  href={`tel:${carePlan.red_flag_banner.emergency_number}`}
                  className="btn"
                  style={{ background: "#fff", color: "#991b1b", textDecoration: "none" }}
                >
                  <PhoneCall size={17} /> {carePlan.red_flag_banner.call_label}
                </a>
                <a
                  href={`https://www.google.com/maps/search/?api=1&query=${encodeURIComponent(
                    carePlan.red_flag_banner.maps_query
                  )}`}
                  target="_blank"
                  rel="noreferrer"
                  className="btn"
                  style={{ background: "rgba(255,255,255,0.16)", color: "#fff", textDecoration: "none" }}
                >
                  <MapPin size={17} /> {carePlan.red_flag_banner.maps_label}
                </a>
              </div>
            </div>
          </div>

          <div className="grid-2">
            {/* Left column: Listen + Daily Checklist */}
            <div>
              <div className="card" style={{ marginBottom: 16 }}>
                <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 12, flexWrap: "wrap" }}>
                  <div>
                    <span className="badge" style={{ marginBottom: 8 }}>
                      {carePlan.language_name} · Plan #{carePlan.plan_id}
                    </span>
                    <h2 style={{ margin: "4px 0 6px", fontSize: "1.2rem" }}>
                      {carePlan.summary_headline}
                    </h2>
                    <p className="muted" style={{ margin: 0 }}>
                      {carePlan.follow_up_reminder}
                    </p>
                  </div>
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={ttsLoading}
                    onClick={() => handleListen(carePlan.caregiver_script, carePlan.language)}
                  >
                    {ttsLoading ? (
                      <>
                        <Loader2 size={17} className="spinner" /> Generating Audio...
                      </>
                    ) : (
                      <>
                        <Volume2 size={17} /> Listen in {LANGUAGES.find((l) => l.code === carePlan.language)?.label}
                      </>
                    )}
                  </button>
                </div>

                {audioUrl && (
                  <audio
                    ref={audioRef}
                    controls
                    src={audioUrl}
                    style={{ width: "100%", marginTop: 12 }}
                  />
                )}
              </div>

              {/* Safety Alerts */}
              {carePlan.safety_alerts.map((alert, idx) => (
                <div key={idx} className={`alert-box ${alert.severity}`}>
                  <div style={{ fontWeight: 700, marginBottom: 4 }}>
                    <ShieldAlert size={16} style={{ verticalAlign: "text-bottom", marginRight: 6 }} />
                    {alert.title}
                  </div>
                  <div style={{ fontSize: "0.9rem", marginBottom: 6 }}>{alert.detail}</div>
                  <div style={{ fontSize: "0.86rem", fontWeight: 600 }}>{alert.action_required}</div>
                </div>
              ))}

              {/* Daily Schedule Checklist */}
              {carePlan.schedule.map((slot) => (
                <div key={slot.slot} className="slot-card">
                  <div className="slot-header">
                    <strong style={{ fontSize: "1.02rem" }}>{slot.slot_title}</strong>
                    <span className="badge">{slot.time_hint}</span>
                  </div>
                  {slot.doses.map((dose) => (
                    <div
                      key={dose.item_id}
                      className={`dose-row ${dose.checked ? "checked" : ""}`}
                      onClick={() => handleToggleDose(dose.item_id, dose.checked)}
                      role="checkbox"
                      aria-checked={dose.checked}
                      tabIndex={0}
                      onKeyDown={(e) => {
                        if (e.key === "Enter" || e.key === " ") {
                          e.preventDefault();
                          handleToggleDose(dose.item_id, dose.checked);
                        }
                      }}
                    >
                      <div>
                        <div style={{ fontWeight: 700 }}>
                          {dose.medication_name} {dose.strength}
                        </div>
                        <div style={{ fontSize: "0.94rem" }}>{dose.dose_text}</div>
                        <div className="muted" style={{ fontSize: "0.8rem" }}>
                          {dose.meal_note}
                          {dose.duration_label ? ` · ${dose.duration_label}` : ""}
                        </div>
                        {dose.caution && (
                          <div style={{ fontSize: "0.8rem", color: "var(--warn)", marginTop: 2 }}>
                            {dose.caution}
                          </div>
                        )}
                      </div>
                      <button
                        type="button"
                        className={`btn ${dose.checked ? "btn-primary" : "btn-secondary"}`}
                        style={{ padding: "6px 10px", flexShrink: 0 }}
                        tabIndex={-1}
                      >
                        <Check size={16} />
                      </button>
                    </div>
                  ))}
                </div>
              ))}
            </div>

            {/* Right column: Live Voice + Live Reasoning Trace + Caregiver Q&A */}
            <div>
              <LiveVoicePanel
                planId={carePlan.plan_id}
                language={carePlan.language}
                languageName={carePlan.language_name}
              />

              <div className="trace-card" style={{ marginBottom: 16 }}>
                <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 8 }}>
                  <span style={{ color: "#94a3b8", fontSize: "0.75rem", fontWeight: 600 }}>
                    LIVE AGENT REASONING TRACE
                  </span>
                  <span style={{ color: "#34d399", fontSize: "0.72rem" }}>Gemini 4 Thinking</span>
                </div>
                {carePlan.reasoning_trace.map((line, i) => (
                  <TraceLine key={i} line={line} />
                ))}
                {carePlan.thought_summary && (
                  <details style={{ marginTop: 10, color: "#cbd5e1", fontSize: "0.78rem" }}>
                    <summary style={{ cursor: "pointer", color: "#38bdf8" }}>
                      View Gemini 4 Thought Summary
                    </summary>
                    <p style={{ whiteSpace: "pre-wrap", marginTop: 6 }}>{carePlan.thought_summary}</p>
                  </details>
                )}
              </div>

              {carePlan.diet_activity_tips.length > 0 && (
                <div className="card" style={{ marginBottom: 16 }}>
                  <h3 className="section-title">Daily Recovery Tips</h3>
                  <ul style={{ margin: 0, paddingLeft: 18 }}>
                    {carePlan.diet_activity_tips.map((tip, i) => (
                      <li key={i} style={{ marginBottom: 6, fontSize: "0.9rem" }}>
                        {tip}
                      </li>
                    ))}
                  </ul>
                </div>
              )}

              <div className="card">
                <h3 className="section-title">
                  <MessageCircle size={18} color="#0b6e63" /> Ask About This Care Plan
                </h3>
                <p className="muted" style={{ fontSize: "0.84rem", marginTop: 0 }}>
                  Answers strictly from your verified discharge plan in {carePlan.language_name}.
                </p>
                <div style={{ maxHeight: 240, overflowY: "auto", marginBottom: 10 }}>
                  {qaMessages.map((msg, i) => (
                    <div
                      key={i}
                      className={`alert-box ${msg.escalate ? "critical" : msg.role === "user" ? "info" : "info"}`}
                      style={{
                        padding: "9px 12px",
                        marginBottom: 8,
                        background: msg.role === "user" ? "#e4f3f0" : msg.escalate ? "var(--danger-bg)" : "#f8fafc",
                      }}
                    >
                      <strong style={{ fontSize: "0.75rem", display: "block", marginBottom: 2 }}>
                        {msg.role === "user" ? "Family" : "Discharge Dost"}
                      </strong>
                      <span style={{ fontSize: "0.88rem" }}>{msg.text}</span>
                    </div>
                  ))}
                </div>
                <div style={{ display: "flex", gap: 8 }}>
                  <input
                    className="input"
                    value={question}
                    onChange={(e) => setQuestion(e.target.value)}
                    placeholder="e.g. Can I take ibuprofen for knee pain?"
                    onKeyDown={(e) => {
                      if (e.key === "Enter") handleAsk();
                    }}
                  />
                  <button
                    type="button"
                    className="btn btn-primary"
                    disabled={asking || !question.trim()}
                    onClick={handleAsk}
                  >
                    {asking ? <Loader2 size={16} className="spinner" /> : "Ask"}
                  </button>
                </div>
              </div>
            </div>
          </div>
        </div>
      )}

      <footer className="disclaimer-bar">{carePlan?.disclaimer || "Clinical safety: Discharge Dost is a comprehension aid, never a medical diagnosis. Illegible handwriting requires pharmacist review. Synthetic demo data only."}</footer>
    </div>
  );
}
