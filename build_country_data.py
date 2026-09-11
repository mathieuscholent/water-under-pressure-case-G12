"""Download and normalize the required country sources.

Run with network access: python3 build_country_data.py
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

from country_codes import canonical_code

ROOT = Path(__file__).parent
RAW = ROOT / "data" / "raw"
RAW.mkdir(parents=True, exist_ok=True)
DOWNLOAD_DATE = date.today().isoformat()
EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
GISCO_URL = "https://gisco-services.ec.europa.eu/distribution/v2/countries/geojson/CNTR_RG_20M_2020_4326.geojson"
EEA_SQL = "https://discodata.eea.europa.eu/sql?query="


def download(url: str, path: Path) -> bytes:
    with urlopen(Request(url, headers={"User-Agent": "water-under-pressure-case-G12/1.0"}), timeout=120) as response:
        body = response.read()
    path.write_bytes(body)
    return body


def eurostat(dataset: str, query: str, filename: str) -> dict:
    body = download(EUROSTAT + dataset + "?lang=en&" + query, RAW / filename)
    return json.loads(body)


def jsonstat_rows(payload: dict) -> list[dict]:
    ids, sizes, values = payload["id"], payload["size"], payload["value"]
    categories = [payload["dimension"][dim]["category"] for dim in ids]
    codes = [[code for code, _ in sorted(cat["index"].items(), key=lambda item: item[1])] for cat in categories]
    rows = []
    entries = values.items() if isinstance(values, dict) else enumerate(values)
    for flat_key, value in entries:
        if value is None:
            continue
        flat = int(flat_key)
        remainder, coords = flat, []
        for size in reversed(sizes):
            coords.append(remainder % size)
            remainder //= size
        coords.reverse()
        rows.append({dim: codes[pos][coord] for pos, (dim, coord) in enumerate(zip(ids, coords))} | {"value": value})
    return rows


def latest_water(rows: list[dict], indicator: str) -> dict[str, dict]:
    selected = {}
    for row in rows:
        if row["wat_proc"] != indicator or row["wat_src"] != "FRW" or row["unit"] != "MIO_M3":
            continue
        year = int(row["time"])
        if year >= 2015 and (row["geo"] not in selected or year > selected[row["geo"]]["year"]):
            selected[canonical_code(row["geo"])] = {"value": row["value"], "year": year}
    return selected


def groundwater() -> tuple[dict[str, dict], dict]:
    sql = ("SELECT countryCode,countryName,gwChemicalStatusValue,euGroundWaterBodyCode "
           "FROM [WISE_WFD].[latest].[GWB_GroundWaterBody] WHERE cYear=2022")
    body = download(EEA_SQL + quote(sql), RAW / "eea_groundwater_2022.json")
    rows = json.loads(body)["results"]
    counts = {}
    for row in rows:
        key = row.get("euGroundWaterBodyCode")
        counts[key] = counts.get(key, 0) + 1
    duplicates = {key: count for key, count in counts.items() if key and count > 1}
    # Keep one record per European groundwater body, deterministically by source order.
    # The latest table may repeat a body across reporting units; the first row is retained.
    unique = {}
    for row in rows:
        unique.setdefault(row.get("euGroundWaterBodyCode"), row)
    aggregate = {}
    for row in unique.values():
        code = canonical_code(row.get("countryCode"))
        if not code:
            continue
        status = str(row.get("gwChemicalStatusValue", "")).strip().upper()
        bucket = "good" if status == "2" else "failing" if status == "3" else "unknown"
        aggregate.setdefault(code, {"name": row.get("countryName"), "good": 0, "failing": 0, "unknown": 0})[bucket] += 1
    result = {}
    for code, item in aggregate.items():
        total = item["good"] + item["failing"] + item["unknown"]
        result[code] = {"good": item["good"] / total, "failing": item["failing"] / total, "unknown": item["unknown"] / total, "records": total}
    return result, {"rawRecords": len(rows), "uniqueRecords": len(unique), "duplicateIds": duplicates, "deduplicationRule": "retain first source row per non-empty euGroundWaterBodyCode; aggregate validated unique bodies by canonical country code"}


def main() -> None:
    water_rows = jsonstat_rows(eurostat("env_wat_abs", "wat_proc=ABS_PWS&wat_src=FRW&unit=MIO_M3", "eurostat_env_wat_abs_pws.json"))
    water_rows += jsonstat_rows(eurostat("env_wat_abs", "wat_proc=ABS_IND&wat_src=FRW&unit=MIO_M3", "eurostat_env_wat_abs_ind.json"))
    p_rows = jsonstat_rows(eurostat("demo_pjan", "unit=NR&age=TOTAL&sex=T&time=2023", "eurostat_demo_pjan_2023.json"))
    p = {canonical_code(row["geo"]): row["value"] for row in p_rows if row["time"] == "2023"}
    supply, manufacturing = latest_water(water_rows, "ABS_PWS"), latest_water(water_rows, "ABS_IND")
    gw, gw_meta = groundwater()
    sql = ("SELECT countryCode,countryName,gwChemicalStatusValue,euGroundWaterBodyCode "
           "FROM [WISE_WFD].[latest].[GWB_GroundWaterBody] WHERE cYear=2022")
    gisco = download(GISCO_URL, RAW / "gisco_cntr_rg_20m_2020_4326.geojson")
    features = json.loads(gisco).get("features", [])
    geo_codes = {canonical_code(f.get("properties", {}).get("CNTR_ID")) for f in features}
    geometry = [{"countryCode": canonical_code(f.get("properties", {}).get("CNTR_ID")), "geometry": f.get("geometry")} for f in features if canonical_code(f.get("properties", {}).get("CNTR_ID"))]
    (ROOT / "data" / "country-geometries.json").write_text(json.dumps(geometry, separators=(",", ":")) + "\n")
    codes = sorted((set(p) | set(supply) | set(manufacturing) | set(gw)) & geo_codes)
    names = {'AL': 'Albania', 'AM': 'Armenia', 'AT': 'Austria', 'AZ': 'Azerbaijan', 'BA': 'Bosnia and Herzegovina', 'BE': 'Belgium', 'BG': 'Bulgaria', 'CH': 'Switzerland', 'CY': 'Cyprus', 'CZ': 'Czechia', 'DE': 'Germany', 'DK': 'Denmark', 'EE': 'Estonia', 'ES': 'Spain', 'FI': 'Finland', 'FR': 'France', 'GE': 'Georgia', 'GR': 'Greece', 'HR': 'Croatia', 'HU': 'Hungary', 'IE': 'Ireland', 'IS': 'Iceland', 'IT': 'Italy', 'LI': 'Liechtenstein', 'LT': 'Lithuania', 'LU': 'Luxembourg', 'LV': 'Latvia', 'MD': 'Moldova', 'ME': 'Montenegro', 'MK': 'North Macedonia', 'MT': 'Malta', 'NL': 'Netherlands', 'NO': 'Norway', 'PL': 'Poland', 'PT': 'Portugal', 'RO': 'Romania', 'RS': 'Serbia', 'SE': 'Sweden', 'SI': 'Slovenia', 'SK': 'Slovakia', 'TR': 'Türkiye', 'UA': 'Ukraine'}
    records = []
    for code in codes:
        w, m, g = supply.get(code), manufacturing.get(code), gw.get(code)
        records.append({"countryCode": code, "countryName": names.get(code, code), "publicWaterSupplyMioM3": w["value"] if w else None, "publicWaterSupplyYear": w["year"] if w else None, "manufacturingWaterMioM3": m["value"] if m else None, "manufacturingWaterYear": m["year"] if m else None, "population2023": p.get(code), "groundwaterGoodShare": g["good"] if g else None, "groundwaterFailingShare": g["failing"] if g else None, "groundwaterUnknownShare": g["unknown"] if g else None, "scarcity": None})
    (ROOT / "data" / "countries.json").write_text(json.dumps(records, indent=2, ensure_ascii=False) + "\n")
    (ROOT / "data" / "countries.js").write_text("window.COUNTRIES_DATA = " + json.dumps(records, ensure_ascii=False, separators=(",", ":")) + ";\n")
    (ROOT / "data" / "country-geometries.js").write_text("window.COUNTRY_GEOMETRIES_DATA = " + json.dumps(geometry, ensure_ascii=False, separators=(",", ":")) + ";\n")
    sources = {"downloadDate": DOWNLOAD_DATE, "countryCodeMapping":{"EL":"GR","UK":"GB"}, "sources":[{"sourceName":"Eurostat env_wat_abs","dataset":"env_wat_abs","url":EUROSTAT+"env_wat_abs","exactQuery":"wat_proc=ABS_PWS and ABS_IND; wat_src=FRW; unit=MIO_M3","variables":["wat_proc","wat_src","unit","geo","time"],"year":"latest non-empty >= 2015","transformations":"select latest observation per canonical country; pre-2015 treated as missing; no interpolation; source observation","deduplicationRule":"none"},{"sourceName":"Eurostat demo_pjan","dataset":"demo_pjan","url":EUROSTAT+"demo_pjan","exactQuery":"unit=NR; age=TOTAL; sex=T; time=2023","variables":["geo","time","value"],"year":2023,"transformations":"source observation"},{"sourceName":"EEA Discodata","dataset":"[WISE_WFD].[latest].[GWB_GroundWaterBody]","url":EEA_SQL,"exactQuery":sql,"variables":["countryCode","countryName","gwChemicalStatusValue","euGroundWaterBodyCode"],"year":2022,"transformations":"map 2 good, 3 failing, U/unknown unknown; derive country shares from validated unique bodies","deduplicationRule":gw_meta["deduplicationRule"]},{"sourceName":"GISCO","dataset":"CNTR_RG_20M_2020_4326.geojson","url":GISCO_URL,"exactQuery":"country outlines download","variables":["CNTR_ID"],"year":2020,"transformations":"canonicalize CNTR_ID for joins"}],"groundwaterValidation":gw_meta,"giscoFeatureCount":len(features),"giscoCanonicalCodes":sorted(geo_codes)}
    (ROOT / "data" / "sources.json").write_text(json.dumps(sources, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__": main()
