"""Live end-to-end check for Part 8 (AI Evidence Verification) against real Groq.

Requires GROQ_API_KEY configured in backend/.env. Uses a living dev DB and the
real multimodal provider, exercising: register -> upload a "pothole" image ->
create a complaint -> POST /vision (real Groq multimodal call) -> GET
/vision-result, plus the negative/edge paths (401/403/404/unrelated image).
"""

import io
import sys
import uuid

import httpx
from PIL import Image, ImageDraw

BASE = "http://localhost:8000/api/v1"
CLIENT = httpx.Client(timeout=180.0)
PASSWORD = "E2ePass#2026"


def unique_email(prefix):
    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def make_pothole_image():
    img = Image.new("RGB", (512, 512), (96, 99, 102))  # asphalt grey
    d = ImageDraw.Draw(img)
    # darker road
    d.rectangle([0, 300, 512, 512], fill=(70, 72, 75))
    # pothole: dark irregular ellipse with lighter rim
    d.ellipse([180, 350, 340, 470], fill=(20, 20, 22))
    d.ellipse([200, 370, 320, 450], fill=(12, 12, 14))
    d.ellipse([150, 420, 260, 460], fill=(24, 24, 26))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def make_unrelated_image():
    img = Image.new("RGB", (512, 512), (110, 170, 230))  # plain sky
    d = ImageDraw.Draw(img)
    d.ellipse([380, 40, 470, 130], fill=(240, 240, 60))  # sun
    d.ellipse([60, 60, 160, 150], fill=(255, 255, 255))  # cloud
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def register(email):
    r = CLIENT.post(
        f"{BASE}/auth/register",
        json={
            "email": email,
            "password": PASSWORD,
            "full_name": "Part 8 E2E",
        },
    )
    assert r.status_code in (200, 201), f"register {r.status_code}: {r.text}"
    token = r.json()["tokens"]["access_token"]
    assert token, "access_token missing"
    return {"Authorization": f"Bearer {token}"}


def upload_media(headers, data, fname):
    r = CLIENT.post(
        f"{BASE}/complaints/media",
        files={"file": (fname, data, "image/jpeg")},
        headers=headers,
    )
    assert r.status_code == 201, f"media {r.status_code}: {r.text}"
    return r.json()["id"]


def create_complaint(headers, media_ids, desc):
    r = CLIENT.post(
        f"{BASE}/complaints",
        json={
            "description": desc,
            "category": "ROAD",
            "media_ids": media_ids,
            "location": {
                "latitude": 18.5204,
                "longitude": 73.8567,
                "address": "MG Road, Pune",
                "source": "gps",
            },
        },
        headers=headers,
    )
    assert r.status_code == 201, f"complaint {r.status_code}: {r.text}"
    return r.json()["id"]


def run_vision(headers, cid):
    r = CLIENT.post(
        f"{BASE}/complaints/{cid}/vision",
        headers=headers,
    )
    assert r.status_code == 200, f"vision {r.status_code}: {r.text}"
    return r.json()


def get_vision_result(headers, cid):
    r = CLIENT.get(f"{BASE}/complaints/{cid}/vision-result", headers=headers)
    assert r.status_code == 200, f"vision-result {r.status_code}: {r.text}"
    return r.json()


def cleanup(email):
    """Best-effort: delete the created user directly via DB to keep dev DB clean."""
    try:
        import asyncio

        from sqlalchemy import select

        from app.db.session import async_session_factory
        from app.models import User

        async def _go():
            async with async_session_factory() as db:
                user = await db.scalar(select(User).where(User.email == email))
                if user is not None:
                    await db.delete(user)
                    await db.commit()

        asyncio.run(_go())
    except Exception:
        pass


def main():
    results = {}

    # --- Positive: valid pothole image -> evidence detected -----------------
    email = unique_email("p8-pot")
    headers = register(email)
    media_id = upload_media(headers, make_pothole_image(), "pothole.jpg")
    cid = create_complaint(
        headers, [media_id], "Deep pothole on MG Road near the school. A car tire fell into it."
    )
    vr = run_vision(headers, cid)
    result = vr.get("result")
    out = vr.get("status")
    results["pothole_status"] = out
    results["pothole_detected"] = result.get("visual_evidence_detected") if result else None
    results["pothole_issue"] = result.get("detected_issue") if result else None
    results["pothole_confidence"] = round(result.get("confidence"), 3) if result else None
    results["pothole_severity"] = result.get("severity") if result else None
    results["pothole_human_review"] = result.get("human_review_required") if result else None
    results["pothole_retry"] = vr.get("retry_allowed")
    print(
        f"[pothole] status={out} issue={results['pothole_issue']} "
        f"conf={results['pothole_confidence']} sev={results['pothole_severity']}"
    )

    getr = get_vision_result(headers, cid)
    results["pothole_result_agent"] = getr.get("agent")
    results["pothole_result_status"] = getr.get("status")
    results["pothole_result_model"] = getr.get("model")

    # --- Edge: unrelated image -> mismatch flagged ---------------------------
    email2 = unique_email("p8-unrel")
    h2 = register(email2)
    m2 = upload_media(h2, make_unrelated_image(), "sky.jpg")
    c2 = create_complaint(h2, [m2], "Pothole on the main road expected.")
    vr2 = run_vision(h2, c2)
    r2 = vr2.get("result") or {}
    results["unrelated_status"] = vr2.get("status")
    results["unrelated_detected"] = r2.get("visual_evidence_detected")
    results["unrelated_mismatch"] = r2.get("mismatch_detected")
    results["unrelated_human_review"] = r2.get("human_review_required")
    print(f"[unrelated] status={vr2.get('status')} mismatch={results['unrelated_mismatch']}")

    # --- Negative: unauthenticated -> 401 -------------------------------------
    r401 = CLIENT.post(f"{BASE}/complaints/{cid}/vision")
    results["no_auth_code"] = r401.status_code

    # --- Negative: other-user access -> 403 -----------------------------------
    email3 = unique_email("p8-oth")
    h3 = register(email3)
    r403 = CLIENT.post(f"{BASE}/complaints/{cid}/vision", headers=h3)
    results["cross_user_code"] = r403.status_code

    # --- Negative: missing complaint -> 404 -----------------------------------
    r404 = CLIENT.post(f"{BASE}/complaints/{uuid.uuid4()}/vision", headers=headers)
    results["missing_cid_code"] = r404.status_code

    for e in (email, email2, email3):
        cleanup(e)

    print("\n=== SUMMARY ===")
    for k, v in results.items():
        print(f"  {k}: {v}")

    ok = (
        out == "SUCCEEDED"
        and results["pothole_detected"] is True
        and results["unrelated_mismatch"] is True
        and results["no_auth_code"] == 401
        and results["cross_user_code"] == 403
        and results["missing_cid_code"] == 404
    )
    print("\nE2E_OK" if ok else "\nE2E_FAILED")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
