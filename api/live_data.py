"""Live public-data adapter with an explicit snapshot fallback."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote
from urllib.request import Request, urlopen

EUROSTAT = "https://ec.europa.eu/eurostat/api/dissemination/statistics/1.0/data/"
EEA_SQL = "https://discodata.eea.europa.eu/sql?query="
ROOT = Path(__file__).resolve().parents[1]


def _get_json(url: str, timeout: int = 12) -> dict:
    request = Request(url, headers={"User-Agent": "water-under-pressure-case-G12/1.0"})
    with urlopen(request, timeout=timeout) as response:
        return json.loads(response.read())


def _rows(payload: dict) -> list[dict]:
    ids, sizes, values = payload["id"], payload["size"], payload["value"]
    codes = []
    for dimension in ids:
        category = payload["dimension"][dimension]["category"]
        codes.append([code for code, _ in sorted(category["index"].items(), key=lambda item: item[1])])
    result = []
    entries = values.items() if isinstance(values, dict) else enumerate(values)
    for key, value in entries:
        if value is None:
            continue
        remainder, coordinates = int(key), []
        for size in reversed(sizes):
            coordinates.append(remainder % size)
            remainder //= size
        coordinates.reverse()
        result.append({dimension: codes[index][coordinate] for index, (dimension, coordinate) in enumerate(zip(ids, coordinates))} | {"value": value})
    return result


def _code(value: str) -> str:
    return {"EL": "GR", "UK": "GB"}.get(value, value)


def _snapshot() -> list[dict]:
    text = (ROOT / "data/countries.js").read_text(encoding="utf-8")
    return json.loads(text.split("=", 1)[1].strip().rstrip(";"))


def fetch_live_countries() -> tuple[list[dict], list[str]]:
    """Fetch current Eurostat observations; return records and source labels."""
    water_url = EUROSTAT + "env_wat_abs?lang=en&wat_proc=ABS_PWS&wat_proc=ABS_IND&wat_src=FRW&unit=MIO_M3"
    population_url = EUROSTAT + "demo_pjan?lang=en&unit=NR&age=TOTAL&sex=T&time=2023"
    water = _rows(_get_json(water_url))
    population = _rows(_get_json(population_url))
    records = _snapshot()
    by_code = {record["countryCode"]: record for record in records}
    for row in population:
        code = _code(row["geo"])
        if code in by_code and row.get("time") == "2023":
            by_code[code]["population2023"] = row["value"]
    for row in water:
        code = _code(row["geo"])
        record = by_code.get(code)
        if not record or row.get("wat_src") != "FRW" or row.get("unit") != "MIO_M3":
            continue
        field = "publicWaterSupply" if row.get("wat_proc") == "ABS_PWS" else "manufacturingWater" if row.get("wat_proc") == "ABS_IND" else None
        if field and (record[field + "Year"] is None or int(row["time"]) >= record[field + "Year"]):
            record[field + "MioM3"], record[field + "Year"] = row["value"], int(row["time"])
    return list(by_code.values()), ["Eurostat env_wat_abs", "Eurostat demo_pjan"]


def live_country_payload() -> dict:
    try:
        countries, sources = fetch_live_countries()
        return {"countries": countries, "sources": sources, "live": True}
    except Exception as error:  # Public APIs can be unavailable or rate limited.
        return {"countries": _snapshot(), "sources": ["data/countries.js snapshot"], "live": False, "warning": str(error)}
