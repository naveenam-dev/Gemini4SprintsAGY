# Discharge Dost

**Safe, vernacular daily care plans from English hospital discharge summaries.**  
Built for **Gemini 4 Sprints** (Health & AI for India) on **Google Cloud Run**.

## Architecture

- **Frontend (`frontend/`)**: React + Vite + TypeScript mobile-first web app (served directly by FastAPI in production).
- **Backend (`backend/`)**: FastAPI + `google-genai` (`>= 3.5.0`) Interactions API:
  1. **Extract Agent (`gemini-4-hydrogen` Vision + Structured JSON)**: Parses photos, PDFs, or text (`1-0-1`, `AC`, `PC`, `SOS`) into strict Pydantic schemas and flags unclear/ambiguous strengths (`5 mg` vs `50 mg`) for pharmacist review.
  2. **Human-in-the-Loop Confirm Screen**: Caregivers verify or edit every extracted line before generating the care plan.
  3. **Safety Reasoner (`backend/safety_rules.py` + `gemini-4-hydrogen` Thinking)**: Deterministic drug interaction & red-flag checks (e.g., Aspirin/Ecosprin + NSAID bleeding risk, Nitrate + PDE5 hypotension, high single doses) layered with Gemini 4 thinking summaries and a live reasoning trace.
  4. **Vernacular Care Plan + Audio + Live Voice (`gemini-3.8-flash-tts` & `gemini-3.8-live`)**: Generates plain-language daily schedules (`Morning`, `Afternoon`, `Night`, `SOS`) in **Kannada**, **Hindi**, **Tamil**, and **English**, WAV read-aloud audio, real-time bidirectional Live voice Q&A over WebSocket (`/ws/live/{plan_id}`), 108 emergency + Google Maps nearest hospital escalation, and stateful care-plan Q&A.
- **Live Demo URL**: `https://discharge-dost-101451598339.asia-south1.run.app`
- **Persistence (`backend/db.py`)**: SQLite care plan + daily checklist storage (`/tmp/discharge_dost.db` on Cloud Run).

### System Architecture

```mermaid
flowchart LR
    subgraph User["Family / Caregiver Browser"]
        UI["React + Vite + TypeScript SPA - App.tsx and LiveVoicePanel.tsx"]
        MIC["16 kHz PCM Mic and 24 kHz Speaker"]
        UI <--> MIC
    end

    subgraph CloudRun["Google Cloud Run - asia-south1 Single Container"]
        API["FastAPI Server - backend/main.py - REST, WebSocket, Static SPA"]
        RULES["Deterministic Safety Rules - backend/safety_rules.py"]
        SVC["Gemini Service Layer - backend/gemini_service.py"]
        DB[("SQLite Store - backend/db.py")]

        API --> RULES
        API --> SVC
        API <--> DB
    end

    subgraph Google["Google Cloud and Gemini APIs"]
        SM["Cloud Secret Manager - gemini-api-key"]
        G4V["Gemini 4 Hydrogen - Vision and Structured JSON"]
        G4T["Gemini 4 Hydrogen - Thinking, Vernacular Plan, Q and A"]
        TTS["Gemini 3.8 Flash TTS - audio/wav Read-Aloud"]
        LIVE["Gemini 3.8 Live - Bidirectional Voice WebSocket"]
        MAPS["Google Maps Emergency Search and 108 Escalation"]
    end

    UI -- "HTTPS: /api/extract, /api/care-plan, /api/tts, /api/ask" --> API
    UI <-- "WSS: /ws/live/{plan_id} PCM Audio and Transcripts" --> API

    SM -. "Injects GEMINI_API_KEY" .-> CloudRun
    SVC -- "Interactions API v1" --> G4V
    SVC -- "Interactions API v1" --> G4T
    SVC -- "Interactions API v1beta" --> TTS
    SVC <-- "Live Connect WS v1beta" --> LIVE
    UI -. "Red-Flag Escalation Link" .-> MAPS
```

### 4-Stage Clinical Flow

```mermaid
sequenceDiagram
    actor Family as Family / Caregiver
    participant UI as React Frontend
    participant API as FastAPI + Safety Rules
    participant G4 as Gemini 4 Hydrogen
    participant Voice as Gemini 3.8 TTS / Live

    Family->>UI: 1. Upload Rx photo/PDF or pick sample + language (kn/hi/ta/en)
    UI->>API: POST /api/extract
    API->>G4: Multimodal Vision + Pydantic JSON Schema (thinking=low)
    G4-->>API: Medications (1-0-1, AC, SOS) + confidence flags
    API-->>UI: ExtractedDischarge

    Family->>UI: 2. Human Confirm (edit/verify doses, catch 5 mg vs 50 mg)
    UI->>API: POST /api/care-plan
    API->>API: run_curated_safety_checks() (Aspirin+NSAID, Nitrate+PDE5)
    API->>G4: Confirmed meds + curated alerts (thinking=medium, summaries=auto)
    G4-->>API: Vernacular schedule + safety alerts + reasoning trace + caregiver_script
    API-->>UI: CarePlanResponse (saved to SQLite)

    Family->>UI: 3. Tap Listen or Start Live Voice
    UI->>API: POST /api/tts
    API->>Voice: gemini-3.8-flash-tts (audio/wav)
    Voice-->>UI: Spoken Kannada / Hindi / Tamil / English care plan

    Family->>UI: Speak or ask follow-up question
    UI->>API: WS /ws/live/{plan_id} (16 kHz PCM) or POST /api/ask
    API->>Voice: gemini-3.8-live session grounded on CarePlan JSON
    Voice-->>UI: 24 kHz PCM audio + live captions
```

## Local Development

```powershell
# Backend
.\.venv\Scripts\python.exe -m uvicorn backend.main:app --reload --port 8000

# Frontend (separate terminal)
cd frontend
npm.cmd install
npm.cmd run dev
```

## Deploy to Google Cloud Run

```powershell
gcloud.cmd run deploy discharge-dost --source . --region asia-south1 --allow-unauthenticated
```
