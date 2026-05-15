"""Receipt storage + retrieval end-to-end test.

Targets the live preview backend.
"""
import os
import io
import sys
import time
import base64
import json
import requests
from pathlib import Path

# Read BACKEND URL from frontend .env (EXPO_PUBLIC_BACKEND_URL)
FRONTEND_ENV = Path("/app/frontend/.env")
BACKEND = None
for line in FRONTEND_ENV.read_text().splitlines():
    if line.startswith("EXPO_PUBLIC_BACKEND_URL="):
        BACKEND = line.split("=", 1)[1].strip().strip('"')
        break
assert BACKEND, "EXPO_PUBLIC_BACKEND_URL not found in frontend/.env"

BASE = BACKEND.rstrip("/") + "/api"
print(f"BACKEND: {BASE}")

results = []
def check(label, cond, info=""):
    status = "PASS" if cond else "FAIL"
    results.append((status, label, info))
    print(f"[{status}] {label}  {info}")
    return cond


# ---------- Helper: build a tiny JPEG ----------
try:
    from PIL import Image
except Exception:
    print("Pillow missing; trying pip install...")
    os.system(f"{sys.executable} -m pip install pillow -q")
    from PIL import Image

img = Image.new("RGB", (50, 50), (200, 50, 50))
buf = io.BytesIO()
img.save(buf, format="JPEG", quality=80)
jpeg_bytes = buf.getvalue()
JPEG_B64 = base64.b64encode(jpeg_bytes).decode("ascii")
print(f"Test JPEG: {len(jpeg_bytes)} bytes, {len(JPEG_B64)} b64 chars")


# ---------- STEP 0: Create a fresh user + group ----------
ts = int(time.time())
reg_payload = {"name": f"ReceiptTester_{ts}"}
r = requests.post(f"{BASE}/auth/register", json=reg_payload, timeout=20)
print("register:", r.status_code)
assert r.status_code == 200, r.text
user_id = r.json()["id"]
print("user_id =", user_id)

grp_payload = {
    "lead_id": user_id,
    "title": f"Receipt Test Bill {ts}",
    "total_amount": 25.00,
    "split_mode": "fast",
    "tax": 0.0,
    "tip": 0.0,
    "items": [],
}
r = requests.post(f"{BASE}/groups", json=grp_payload, timeout=20)
print("create group:", r.status_code)
assert r.status_code == 200, r.text
group_id = r.json()["id"]
print("group_id =", group_id)


# ---------- STEP 1: POST /api/receipts/store (valid JPEG) ----------
print("\n=== STEP 1: POST /api/receipts/store (valid) ===")
body = {"group_id": group_id, "image_base64": JPEG_B64, "mime": "image/jpeg"}
r = requests.post(f"{BASE}/receipts/store", json=body, timeout=30)
print("status:", r.status_code, "body:", r.text[:300])
ok1 = check("Step1: HTTP 200 on /receipts/store", r.status_code == 200, f"status={r.status_code}")
j1 = r.json() if ok1 else {}
receipt_id_1 = j1.get("receipt_id")
check("Step1: response has 'receipt_id'", bool(receipt_id_1), f"receipt_id={receipt_id_1}")


# ---------- STEP 2: GET /api/receipts/{receipt_id} ----------
print("\n=== STEP 2: GET /api/receipts/{receipt_id} ===")
r = requests.get(f"{BASE}/receipts/{receipt_id_1}", timeout=20)
print("status:", r.status_code, "body keys:", list(r.json().keys()) if r.status_code == 200 else r.text[:200])
ok2 = check("Step2: HTTP 200 on /receipts/{id}", r.status_code == 200, f"status={r.status_code}")
if ok2:
    j2 = r.json()
    check("Step2: response has 'image_base64'", bool(j2.get("image_base64")))
    check("Step2: response has 'mime'", bool(j2.get("mime")), f"mime={j2.get('mime')}")
    # base64 may differ if backend recompressed; verify it at least decodes as a valid JPEG
    try:
        decoded = base64.b64decode(j2.get("image_base64") or "")
        im_check = Image.open(io.BytesIO(decoded))
        im_check.verify()
        check("Step2: stored image_base64 decodes to valid image (possibly recompressed)",
              True, f"decoded={len(decoded)} bytes, format={im_check.format}")
    except Exception as e:
        check("Step2: stored image_base64 decodes to valid image", False, f"err={e}")


# ---------- STEP 3: GET /api/groups/{group_id}/receipts ----------
print("\n=== STEP 3: GET /api/groups/{group_id}/receipts (1 receipt) ===")
r = requests.get(f"{BASE}/groups/{group_id}/receipts", timeout=20)
print("status:", r.status_code, "body:", r.text[:400])
ok3 = check("Step3: HTTP 200 on /groups/{id}/receipts", r.status_code == 200)
if ok3:
    j3 = r.json()
    items = j3.get("items") or []
    check("Step3: 'items' is a list with >=1 entry", isinstance(items, list) and len(items) >= 1,
          f"len(items)={len(items)}")
    has_new = any((it.get("receipt_id") == receipt_id_1) for it in items)
    check("Step3: items contains the new receipt_id", has_new)
    check("Step3: last_receipt_id matches the new receipt", j3.get("last_receipt_id") == receipt_id_1,
          f"last_receipt_id={j3.get('last_receipt_id')}")


# ---------- STEP 4: Store a SECOND receipt and re-list ----------
print("\n=== STEP 4: Store second receipt, expect items=2 ===")
img2 = Image.new("RGB", (60, 60), (50, 200, 50))
buf2 = io.BytesIO()
img2.save(buf2, format="JPEG", quality=80)
JPEG_B64_2 = base64.b64encode(buf2.getvalue()).decode("ascii")

body2 = {"group_id": group_id, "image_base64": JPEG_B64_2, "mime": "image/jpeg"}
r = requests.post(f"{BASE}/receipts/store", json=body2, timeout=30)
print("store2 status:", r.status_code, r.text[:200])
ok4a = check("Step4a: second /receipts/store returns 200", r.status_code == 200)
receipt_id_2 = r.json().get("receipt_id") if ok4a else None

r = requests.get(f"{BASE}/groups/{group_id}/receipts", timeout=20)
ok4b = check("Step4b: GET /groups/{id}/receipts returns 200", r.status_code == 200)
if ok4b:
    j4 = r.json()
    items = j4.get("items") or []
    check("Step4c: items length == 2", len(items) == 2, f"len={len(items)}")
    check("Step4d: last_receipt_id == second receipt", j4.get("last_receipt_id") == receipt_id_2,
          f"last={j4.get('last_receipt_id')}, expected={receipt_id_2}")


# ---------- STEP 5: Invalid base64 → 400 ----------
print("\n=== STEP 5: Invalid base64 → 400 ===")
bad = {"group_id": group_id, "image_base64": "not-base64-at-all!!!@@@###", "mime": "image/jpeg"}
r = requests.post(f"{BASE}/receipts/store", json=bad, timeout=20)
print("status:", r.status_code, "body:", r.text[:300])
check("Step5: invalid base64 returns HTTP 400", r.status_code == 400, f"status={r.status_code}")


# ---------- STEP 6: Unknown receipt id → 404 ----------
print("\n=== STEP 6: Unknown receipt id → 404 ===")
r = requests.get(f"{BASE}/receipts/unknown_id_xyz", timeout=20)
print("status:", r.status_code, "body:", r.text[:200])
check("Step6: unknown receipt id returns HTTP 404", r.status_code == 404, f"status={r.status_code}")


# ---------- SUMMARY ----------
print("\n" + "=" * 60)
print("SUMMARY")
print("=" * 60)
passes = sum(1 for s, _, _ in results if s == "PASS")
fails = sum(1 for s, _, _ in results if s == "FAIL")
print(f"PASS: {passes}  FAIL: {fails}")
for s, l, i in results:
    print(f"  [{s}] {l}  {i}")
sys.exit(0 if fails == 0 else 1)
