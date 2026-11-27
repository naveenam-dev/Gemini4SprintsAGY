"""End-to-end live verification against FastAPI + Gemini 4 Vision/Thinking + Gemini 3.8 TTS & Live."""
from __future__ import annotations

import asyncio
import json
import subprocess
import sys
import time
import requests
import websockets

BASE_URL = "http://127.0.0.1:8765"
WS_BASE_URL = "ws://127.0.0.1:8765"


def wait_for_server(timeout_s: float = 20.0) -> None:
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        try:
            r = requests.get(f"{BASE_URL}/api/health", timeout=2)
            if r.status_code == 200:
                return
        except requests.RequestException:
            pass
        time.sleep(0.4)
    raise RuntimeError("Server did not become healthy in time")


def main() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "backend.main:app", "--host", "127.0.0.1", "--port", "8765"],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    try:
        wait_for_server()

        # 1. Frontend SPA root
        r_root = requests.get(f"{BASE_URL}/", timeout=5)
        assert r_root.status_code == 200 and "Discharge Dost" in r_root.text, "Frontend root failed"
        print("1. GET / -> 200 OK (React SPA served)")

        # 2. Health & Samples
        health = requests.get(f"{BASE_URL}/api/health", timeout=5).json()
        assert health["gemini_key_configured"] is True
        samples = requests.get(f"{BASE_URL}/api/samples", timeout=5).json()["samples"]
        assert len(samples) == 3
        print(f"2. GET /api/health & /api/samples -> OK ({len(samples)} samples)")

        # 3. Extract (Step 1)
        r_ext = requests.post(
            f"{BASE_URL}/api/extract",
            data={"raw_text": samples[0]["raw_text"]},
            timeout=60,
        )
        assert r_ext.status_code == 200, r_ext.text
        extracted = r_ext.json()
        med_names = [m["name"] for m in extracted["medications"]]
        print(f"3. POST /api/extract -> {len(med_names)} meds: {med_names}")
        assert len(med_names) >= 3

        # 4. Care Plan + Safety Check + Kannada Localization (Step 3)
        r_plan = requests.post(
            f"{BASE_URL}/api/care-plan",
            json={"extracted": extracted, "language": "kn", "hospital_city": "Bengaluru"},
            timeout=90,
        )
        assert r_plan.status_code == 200, r_plan.text
        plan = r_plan.json()
        print(f"4. POST /api/care-plan (kn) -> plan_id={plan['plan_id']}, slots={len(plan['schedule'])}, alerts={len(plan['safety_alerts'])}")
        assert len(plan["schedule"]) >= 1
        assert len(plan["safety_alerts"]) >= 1
        assert plan["red_flag_banner"]["emergency_number"] == "108"

        # 5. Checklist toggle
        first_item = plan["schedule"][0]["doses"][0]
        r_chk = requests.patch(
            f"{BASE_URL}/api/plans/{plan['plan_id']}/checklist",
            json={"item_id": first_item["item_id"], "checked": True},
            timeout=10,
        )
        assert r_chk.status_code == 200
        assert r_chk.json()["schedule"][0]["doses"][0]["checked"] is True
        print("5. PATCH /api/plans/{id}/checklist -> persisted checked=True")

        # 6. Gemini 3.8 TTS audio synthesis
        r_tts = requests.post(
            f"{BASE_URL}/api/tts",
            json={"text": plan["caregiver_script"], "language": "kn"},
            timeout=60,
        )
        assert r_tts.status_code == 200, r_tts.text
        assert r_tts.headers["content-type"].startswith("audio/wav")
        assert len(r_tts.content) > 5000
        print(f"6. POST /api/tts -> audio/wav ({len(r_tts.content)} bytes)")

        # 7. Caregiver Q&A
        r_ask = requests.post(
            f"{BASE_URL}/api/ask",
            json={
                "plan_id": plan["plan_id"],
                "question": "Can I take ibuprofen for body pain?",
                "language": "kn",
            },
            timeout=60,
        )
        assert r_ask.status_code == 200, r_ask.text
        ans = r_ask.json()
        assert len(ans["answer"]) > 10
        print(f"7. POST /api/ask -> answer length={len(ans['answer'])}, escalate_108={ans['escalate_108']}")

        # 8. Vision image extract on bundled sample PNG
        r_img = requests.get(f"{BASE_URL}/samples/cardiac-discharge.png", timeout=10)
        assert r_img.status_code == 200 and len(r_img.content) > 5000
        r_vis = requests.post(
            f"{BASE_URL}/api/extract",
            files={"file": ("cardiac-discharge.png", r_img.content, "image/png")},
            timeout=60,
        )
        assert r_vis.status_code == 200, r_vis.text
        vis_meds = [m["name"] for m in r_vis.json()["medications"]]
        print(f"8. Vision POST /api/extract (cardiac-discharge.png) -> {vis_meds}")
        assert len(vis_meds) >= 3

        # 9. Gemini 3.8 Live WebSocket Q&A
        async def check_live() -> None:
            async with websockets.connect(
                f"{WS_BASE_URL}/ws/live/{plan['plan_id']}?language=en"
            ) as ws:
                ready = json.loads(await ws.recv())
                assert ready["type"] == "ready", ready
                await ws.send(json.dumps({"type": "text", "text": "Which tablet is taken in the morning?"}))
                got_audio = False
                transcript = []
                while True:
                    msg = json.loads(await asyncio.wait_for(ws.recv(), timeout=25))
                    if msg["type"] == "audio":
                        got_audio = True
                    elif msg["type"] == "output_transcript":
                        transcript.append(msg["text"])
                    elif msg["type"] == "turn_complete":
                        break
                assert got_audio, "Expected Live PCM audio chunks"
                print(f"9. WS /ws/live/{plan['plan_id']} -> audio=True, transcript={''.join(transcript)!r}")

        asyncio.run(check_live())
        print("ALL E2E CHECKS PASSED!")
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()


if __name__ == "__main__":
    main()
