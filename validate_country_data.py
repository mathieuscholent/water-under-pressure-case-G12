"""Validation gate for generated country data."""
import json
from pathlib import Path
from country_codes import canonical_code

ROOT = Path(__file__).parent
COUNTRIES = json.loads((ROOT / "data/countries.json").read_text())
SOURCES = json.loads((ROOT / "data/sources.json").read_text())
errors = []
codes = [r["countryCode"] for r in COUNTRIES]
if len(codes) != len(set(codes)): errors.append("duplicate final country records")
if any(r["publicWaterSupplyYear"] is not None and r["publicWaterSupplyYear"] < 2015 for r in COUNTRIES): errors.append("pre-2015 supply observation")
if any(r["manufacturingWaterYear"] is not None and r["manufacturingWaterYear"] < 2015 for r in COUNTRIES): errors.append("pre-2015 manufacturing observation")
for r in COUNTRIES:
    shares = [r[k] for k in ("groundwaterGoodShare", "groundwaterFailingShare", "groundwaterUnknownShare")]
    if any(v is not None and not 0 <= v <= 1 for v in shares): errors.append(f"invalid groundwater share {r['countryCode']}")
    if any(v is not None for v in shares) and abs(sum(v or 0 for v in shares) - 1) > 1e-9: errors.append(f"groundwater shares do not sum {r['countryCode']}")
if SOURCES["groundwaterValidation"]["duplicateIds"]: print("Groundwater duplicate IDs:", SOURCES["groundwaterValidation"]["duplicateIds"])
for wanted in ["FR","DE","ES","IT","NL","PL"]:
    r = next((x for x in COUNTRIES if x["countryCode"] == wanted), None)
    if not r: errors.append(f"missing requested country {wanted}")
print("Validation status:", "PASS" if not errors else "FAIL")
if errors: print("Errors:", errors)
print("Countries:", len(COUNTRIES), "GISCO features:", SOURCES["giscoFeatureCount"])
