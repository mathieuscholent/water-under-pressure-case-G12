"""Central country-code normalization for all source joins."""

SOURCE_TO_CANONICAL = {"EL": "GR", "UK": "GB"}
CANONICAL_TO_SOURCE = {value: key for key, value in SOURCE_TO_CANONICAL.items()}


def canonical_code(code: str | None) -> str | None:
    if code is None:
        return None
    value = code.strip().upper()
    return SOURCE_TO_CANONICAL.get(value, value)
