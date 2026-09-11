"""Pure, configurable water-price calculation functions."""

from dataclasses import dataclass, asdict
from typing import Any, Mapping


@dataclass(frozen=True)
class PricingConfig:
    scarcity_multiplier_coefficient: float = 0.50
    quality_multiplier_coefficient: float = 0.40
    pollution_multiplier_coefficient: float = 0.60
    consumption_multiplier_coefficient: float = 0.20
    consumption_reference_m3: float = 200.0


def _unit_interval(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not 0 <= value <= 1:
        raise ValueError(f"{name} must be a number between 0 and 1")
    return float(value)


def _nonnegative(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or value < 0:
        raise ValueError(f"{name} must be a non-negative number")
    return float(value)


def scarcity_multiplier(score: float, config: PricingConfig) -> float:
    return 1 + config.scarcity_multiplier_coefficient * _unit_interval(score, "scarcity_score")


def quality_multiplier(score: float, config: PricingConfig) -> float:
    # A low quality score means more treatment is required.
    return 1 + config.quality_multiplier_coefficient * (1 - _unit_interval(score, "water_quality_score"))


def pollution_multiplier(score: float, config: PricingConfig) -> float:
    return 1 + config.pollution_multiplier_coefficient * _unit_interval(score, "pollution_score")


def consumption_multiplier(annual_consumption_m3: float, config: PricingConfig) -> float:
    consumption = _nonnegative(annual_consumption_m3, "annual_consumption_m3")
    return 1 + config.consumption_multiplier_coefficient * min(
        consumption / config.consumption_reference_m3, 1
    )


def calculate_price(inputs: Mapping[str, Any], config: PricingConfig | None = None) -> dict[str, Any]:
    """Calculate one price without side effects; all monetary values are per m3."""
    config = config or PricingConfig()
    user_type = inputs.get("user_type")
    if user_type not in {"household", "company"}:
        raise ValueError("user_type must be 'household' or 'company'")

    consumption = _nonnegative(inputs.get("annual_consumption_m3"), "annual_consumption_m3")
    scarcity = _unit_interval(inputs.get("scarcity_score"), "scarcity_score")
    quality = _unit_interval(inputs.get("water_quality_score"), "water_quality_score")
    pollution = inputs.get("pollution_score", 0)
    if user_type == "company":
        pollution = _unit_interval(pollution, "pollution_score")
    elif "pollution_score" in inputs:
        _unit_interval(pollution, "pollution_score")

    floor_key = f"{user_type}_price_floor"
    ceiling_key = f"{user_type}_price_ceiling"
    base_key = f"base_{user_type}_price"
    floor = _nonnegative(inputs.get(floor_key), floor_key)
    ceiling = _nonnegative(inputs.get(ceiling_key), ceiling_key)
    base = _nonnegative(inputs.get(base_key), base_key)
    if floor > ceiling:
        raise ValueError(f"{floor_key} cannot exceed {ceiling_key}")
    if config.consumption_reference_m3 <= 0:
        raise ValueError("consumption_reference_m3 must be positive")
    coefficients = (config.scarcity_multiplier_coefficient, config.quality_multiplier_coefficient,
                    config.pollution_multiplier_coefficient, config.consumption_multiplier_coefficient)
    if any(value < 0 for value in coefficients):
        raise ValueError("multiplier coefficients must be non-negative")

    factors = {
        "scarcity": scarcity_multiplier(scarcity, config),
        "water_quality": quality_multiplier(quality, config),
        "consumption": consumption_multiplier(consumption, config),
        "pollution": pollution_multiplier(pollution, config) if user_type == "company" else 1.0,
    }
    unclamped = base
    for factor in factors.values():
        unclamped *= factor
    final_price = min(ceiling, max(floor, unclamped))
    return {
        "price_per_m3": final_price,
        "unclamped_price_per_m3": unclamped,
        "floor": floor,
        "ceiling": ceiling,
        "decomposition": {"base_price": base, "multipliers": factors},
        "clamp": "floor" if unclamped < floor else "ceiling" if unclamped > ceiling else None,
    }
