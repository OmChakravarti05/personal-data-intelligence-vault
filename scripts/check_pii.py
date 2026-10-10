import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))

from app.services.pii_detection import detect_pii, redact_text

EMAIL = "priya.sharma@example.com"
PHONE = "+91 98765 43210"
CARD = "4111 1111 1111 1111"
PAN = "ABCDE1234F"
AADHAAR = "2345 6789 0123"

sample = (
    f"Contact: {EMAIL}\n"
    f"Mobile: {PHONE}\n"
    f"Card: {CARD}\n"
    f"PAN: {PAN}\n"
    f"Aadhaar: {AADHAAR}\n"
    "The quarterly budget review is on Monday.\n"
)

matches = detect_pii(sample)
found = {m.category for m in matches}
for label, category in [
    ("email", "EMAIL_ADDRESS"),
    ("phone", "PHONE_NUMBER"),
    ("credit card", "CREDIT_CARD"),
    ("pan", "PAN_NUMBER"),
    ("aadhaar", "AADHAAR_NUMBER"),
]:
    print(f"{label} detected:", category in found)

redacted = redact_text(sample, matches)
raw_values = [EMAIL, PHONE, CARD, PAN, AADHAAR]
print("raw values removed from redaction:", not any(v in redacted for v in raw_values))
print("harmless text kept:", "quarterly budget review" in redacted)
print("matches hold no raw text:", not any(hasattr(m, "text") for m in matches))
print("empty text gives no matches:", detect_pii("   ") == [])

big = "The team met to review the schedule and plan the next release.\n" * 2000
big += f"Contact: {EMAIL}\n"
big_matches = detect_pii(big)
print("large text scanned in blocks:", any(m.category == "EMAIL_ADDRESS" for m in big_matches))
print("offsets point at the value:", big[
    next(m for m in big_matches if m.category == "EMAIL_ADDRESS").start :
    next(m for m in big_matches if m.category == "EMAIL_ADDRESS").end
] == EMAIL)

print()
print("redacted preview:")
print(redacted)