from __future__ import annotations

SAMPLES = [
    {
        "id": "cardiac_discharge",
        "title": "Post-Cardiac Discharge (English Rx + Painkiller Interaction)",
        "badge": "Cardiac · Safety Flag Demo",
        "summary": "Metoprolol 25 mg 1-0-1, Ecosprin 75 mg 0-1-0 AC, Sorbitrate 5 mg SOS + Ibuprofen 400 mg SOS",
        "raw_text": (
            "ST. MARTHA'S CARE HOSPITAL - BENGALURU (SYNTHETIC DEMO)\n"
            "DISCHARGE SUMMARY\n"
            "Diagnosis: Unstable Angina / Post-PCI Observation (Stable at discharge)\n"
            "Discharge Date: 27 Nov 2026\n"
            "Follow-up: Cardiology OPD on 07 Dec 2026 (10:00 AM)\n\n"
            "Medications on Discharge:\n"
            "1. Tab. Metoprolol 25 mg  1-0-1 x 30 days (PC - after breakfast & dinner)\n"
            "2. Tab. Ecosprin 75 mg    0-1-0 x 30 days (AC - before lunch)\n"
            "3. Tab. Sorbitrate 5 mg   SL SOS for chest tightness\n"
            "4. Tab. Ibuprofen 400 mg  SOS for body ache\n\n"
            "Advice & Red Flags:\n"
            "- Low salt diet, avoid sudden heavy exertion for 2 weeks.\n"
            "- If chest pain lasts >5 min, breathlessness, or dizziness: call 108 / go to emergency immediately."
        ),
    },
    {
        "id": "handwritten_ambiguous",
        "title": "Faint Handwritten Note (Ambiguous 5 mg vs 50 mg Check)",
        "badge": "Human-in-the-Loop Check",
        "summary": "Includes an unclear strength ('5 mg or 50 mg?') that triggers pharmacist review before care plan.",
        "raw_text": (
            "CITY GENERAL CLINIC - CHENNAI (SYNTHETIC DEMO)\n"
            "DISCHARGE NOTE\n"
            "Diagnosis: Hypertension & Type 2 Diabetes Follow-up\n"
            "Follow-up: Medicine OPD after 14 days\n\n"
            "Rx:\n"
            "1. Tab. Amlodipine [handwriting smudged: looks like 5 mg or 50 mg?] 1-0-0 x 30d\n"
            "2. Tab. Metformin 500 mg 1-0-1 after meals x 30d\n"
            "3. Tab. Atorvastatin 10 mg 0-0-1 at night x 30d\n\n"
            "Red Flags: Severe headache, blurred vision, chest pain, or fainting -> Emergency / 108."
        ),
    },
    {
        "id": "post_surgery",
        "title": "Post-Ortho Surgery Discharge (Antibiotic + Stomach Guard)",
        "badge": "Post-Op · Meal Timing",
        "summary": "Pantoprazole AC before breakfast, Augmentin 625 mg PC, Paracetamol 650 mg SOS.",
        "raw_text": (
            "KAVERI ORTHO CARE - MYSURU (SYNTHETIC DEMO)\n"
            "DISCHARGE SUMMARY\n"
            "Diagnosis: Right Ankle ORIF Post-Op Day 3\n"
            "Follow-up: Ortho Dressing Review on 04 Dec 2026\n\n"
            "Medications:\n"
            "1. Cap. Pantoprazole 40 mg   1-0-0 AC (30 mins before breakfast) x 10 days\n"
            "2. Tab. Augmentin 625 mg     1-0-1 PC (after meals) x 7 days\n"
            "3. Tab. Paracetamol 650 mg   SOS for fever or pain (max 3/day)\n\n"
            "Advice: Keep leg elevated, keep dressing dry. High fever, pus, or severe swelling -> call 108 / visit ER."
        ),
    },
]
