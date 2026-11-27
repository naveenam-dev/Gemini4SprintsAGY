from __future__ import annotations

import re
from .schemas import ExtractedDischarge, SafetyAlert


ANTIPLATELETS_AND_ANTICOAGULANTS = {
    "ecosprin",
    "aspirin",
    "clopidogrel",
    "clopivas",
    "plavix",
    "ticagrelor",
    "brilinta",
    "prasugrel",
    "warfarin",
    "acenocoumarol",
    "acitrom",
    "rivaroxaban",
    "apixaban",
    "dabigatran",
}

NSAIDS = {
    "ibuprofen",
    "brufen",
    "combiflam",
    "diclofenac",
    "voveran",
    "aceclofenac",
    "zerodol",
    "naproxen",
    "ketorolac",
    "piroxicam",
    "etoricoxib",
    "mefenamic",
}

NITRATES = {
    "sorbitrate",
    "isosorbide",
    "nitroglycerin",
    "glyceryl trinitrate",
    "angised",
    "monotrate",
}

PDE5_INHIBITORS = {
    "sildenafil",
    "viagra",
    "tadalafil",
    "cialis",
    "vardenafil",
}

BETA_BLOCKERS = {
    "metoprolol",
    "atenolol",
    "bisoprolol",
    "carvedilol",
    "propranolol",
    "nebivolol",
}


def _normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9\s]", " ", text.lower()).strip()


def _matches_any(med_name: str, keywords: set[str]) -> bool:
    norm = _normalize(med_name)
    return any(kw in norm for kw in keywords)


def _extract_mg(strength: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*mg\b", strength.lower())
    if match:
        return float(match.group(1))
    return None


def run_curated_safety_checks(extracted: ExtractedDischarge) -> tuple[list[SafetyAlert], list[str]]:
    """Run deterministic clinical safety rules over confirmed medications."""
    alerts: list[SafetyAlert] = []
    trace: list[str] = []

    antiplatelets = [m for m in extracted.medications if _matches_any(m.name, ANTIPLATELETS_AND_ANTICOAGULANTS)]
    nsaids = [m for m in extracted.medications if _matches_any(m.name, NSAIDS)]
    nitrates = [m for m in extracted.medications if _matches_any(m.name, NITRATES)]
    pde5 = [m for m in extracted.medications if _matches_any(m.name, PDE5_INHIBITORS)]
    beta_blockers = [m for m in extracted.medications if _matches_any(m.name, BETA_BLOCKERS)]

    med_summary = ", ".join(f"{m.name} {m.strength}".strip() for m in extracted.medications)
    trace.append(
        f"[CHECK] Verified {len(extracted.medications)} confirmed medicines: {med_summary or 'none'}"
    )

    # 1. Bleeding risk: Antiplatelet/Anticoagulant + NSAID (or general OTC NSAID caution)
    if antiplatelets and nsaids:
        names = [f"{m.name} {m.strength}".strip() for m in antiplatelets + nsaids]
        alerts.append(
            SafetyAlert(
                severity="critical",
                title="Bleeding Risk: Blood Thinner + Painkiller (NSAID)",
                detail=(
                    f"{', '.join(m.name for m in antiplatelets)} combined with "
                    f"{', '.join(m.name for m in nsaids)} significantly increases stomach and GI bleeding risk."
                ),
                action_required="Ask your pharmacist or doctor before taking this painkiller.",
                related_medications=names,
                source="curated_rule",
            )
        )
        trace.append(
            f"[FLAG] {' + '.join(names)} -> bleeding risk (Aspirin/blood thinner + NSAID) -> ask pharmacist"
        )
    elif antiplatelets:
        names = [f"{m.name} {m.strength}".strip() for m in antiplatelets]
        alerts.append(
            SafetyAlert(
                severity="warning",
                title="Ask Pharmacist Before Any Painkiller",
                detail=(
                    f"Because you take {', '.join(m.name for m in antiplatelets)}, avoid over-the-counter "
                    "painkillers like Ibuprofen, Diclofenac, or Combiflam unless approved by your doctor."
                ),
                action_required="Ask your pharmacist before any painkiller.",
                related_medications=names,
                source="curated_rule",
            )
        )
        trace.append(
            f"[FLAG] {', '.join(names)} -> antiplatelet active -> warn against OTC NSAID painkillers"
        )

    # 2. Nitrate + PDE5 inhibitor
    if nitrates and pde5:
        names = [f"{m.name} {m.strength}".strip() for m in nitrates + pde5]
        alerts.append(
            SafetyAlert(
                severity="critical",
                title="Dangerous Blood Pressure Drop Risk",
                detail="Combining nitrates (such as Sorbitrate) with PDE5 inhibitors can cause life-threatening low blood pressure.",
                action_required="Do NOT take together; contact your doctor immediately.",
                related_medications=names,
                source="curated_rule",
            )
        )
        trace.append(f"[FLAG] {' + '.join(names)} -> severe hypotension risk -> critical alert")

    # 3. Duplicate Beta-Blocker check
    if len(beta_blockers) > 1:
        names = [f"{m.name} {m.strength}".strip() for m in beta_blockers]
        alerts.append(
            SafetyAlert(
                severity="warning",
                title="Multiple Heart-Rate Medicines Detected",
                detail="More than one beta-blocker is listed. Confirm with your doctor or pharmacist that both are intentional.",
                action_required="Verify with prescribing doctor before taking both.",
                related_medications=names,
                source="curated_rule",
            )
        )
        trace.append(f"[FLAG] Duplicate beta-blockers detected ({', '.join(names)})")

    # 4. High-dose / Ambiguity / Pharmacist review flags
    for med in extracted.medications:
        mg = _extract_mg(med.strength)
        if _matches_any(med.name, {"metoprolol"}) and mg is not None and mg >= 200:
            alerts.append(
                SafetyAlert(
                    severity="warning",
                    title=f"Unusually High Dose Check: {med.name} {med.strength}",
                    detail="Metoprolol 200 mg+ per tablet is high—verify whether the prescription says 25 mg or 50 mg.",
                    action_required="Confirm tablet strength on the physical bottle with your pharmacist.",
                    related_medications=[f"{med.name} {med.strength}"],
                    source="curated_rule",
                )
            )
            trace.append(f"[FLAG] High single-tablet dose on {med.name} ({med.strength}) -> verify bottle")

        if med.needs_pharmacist_review or med.confidence == "low":
            alerts.append(
                SafetyAlert(
                    severity="warning",
                    title=f"Pharmacist Verification Needed: {med.name}",
                    detail=med.illegible_reason or "Handwriting or dosage strength had low extraction confidence.",
                    action_required="Show the original discharge paper to a pharmacist before the first dose.",
                    related_medications=[f"{med.name} {med.strength}".strip()],
                    source="curated_rule",
                )
            )
            trace.append(f"[FLAG] Low-confidence line '{med.name} {med.strength}' -> pharmacist review")

    if not alerts:
        trace.append("[CHECK] Curated interaction rules clear; proceeding with clinical reasoning check")

    return alerts, trace
