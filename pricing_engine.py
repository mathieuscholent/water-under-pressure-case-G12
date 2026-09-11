"""Pure, configurable water-price calculation functions."""

from dataclasses import dataclass, asdict
from typing import Any, Mapping
import csv
import io
from urllib.request import urlopen


@dataclass(frozen=True)
class PricingConfig:
    scarcity_multiplier_coefficient: float = 0.50
    treatment_cost_per_intensity_m3: float = 0.40
    pollution_multiplier_coefficient: float = 0.60
    consumption_multiplier_coefficient: float = 0.20
    consumption_reference_m3: float = 200.0


EEA_WEI_CSV_URL = "https://www.eea.europa.eu/en/analysis/maps-and-charts/water-exploitation-index-plus-chart_2/@@download/file"


def wei_to_scarcity_score(raw_percent: Any) -> float:
    """Prototype-only normalization: 0% WEI+ => 0, 40%+ => 1."""
    value = _nonnegative(raw_percent, "wei_plus_percent")
    return min(value, 40.0) / 40.0


def fetch_eea_scarcity(geography: str, year: int | None = None, timeout: int = 15) -> dict[str, Any]:
    """Retrieve the EEA's country WEI+ CSV and return raw plus separately-derived data."""
    if not isinstance(geography, str) or not geography.strip():
        raise ValueError("geography must be a non-empty country name or code")
    with urlopen(EEA_WEI_CSV_URL, timeout=timeout) as response:
        rows = list(csv.DictReader(io.TextIOWrapper(response, encoding="utf-8-sig")))
    if not rows:
        raise ValueError("EEA WEI+ download returned no rows")
    def find(row, words):
        return next((value for key, value in row.items() if any(word in key.lower() for word in words)), "")
    matches = [row for row in rows if geography.casefold() in find(row, ("country", "geo", "name", "code")).casefold()]
    if year is not None:
        matches = [row for row in matches if str(year) in find(row, ("year", "time", "period"))]
    if not matches:
        raise ValueError(f"No EEA WEI+ value found for geography '{geography}'")
    row = matches[-1]
    raw_text = find(row, ("wei", "value", "percent", "%"))
    try:
        raw = float(raw_text.replace(",", ".").replace("%", "").strip())
    except (AttributeError, ValueError) as error:
        raise ValueError("EEA WEI+ value was not numeric") from error
    return {"geography": geography, "raw_public_data_value": raw,
            "raw_unit": "percent", "source": "European Environment Agency WEI+ country CSV",
            "source_url": EEA_WEI_CSV_URL, "date_year": find(row, ("year", "time", "period")) or "1990–2017",
            "transformation": "prototype normalization: min(max(raw WEI+ %, 0), 40) / 40",
            "scarcity_score": wei_to_scarcity_score(raw),
            "official_metric_disclaimer": "The 0–1 score is calculated by this prototype; it is not an official EEA or EU metric."}


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


def treatment_cost(intensity: float, config: PricingConfig) -> float:
    """Return the additive treatment cost for a 0–1 treatment requirement score."""
    return _unit_interval(intensity, "treatment_intensity_score") * config.treatment_cost_per_intensity_m3


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
    treatment_intensity = _unit_interval(
        inputs.get("treatment_intensity_score"), "treatment_intensity_score"
    )
    if "water_quality_score" in inputs:
        raise ValueError("use treatment_intensity_score instead of water_quality_score")
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
    coefficients = (config.scarcity_multiplier_coefficient,
                    config.pollution_multiplier_coefficient,
                    config.consumption_multiplier_coefficient,
                    config.treatment_cost_per_intensity_m3)
    if any(value < 0 for value in coefficients):
        raise ValueError("pricing coefficients must be non-negative")

    factors = {
        "scarcity": scarcity_multiplier(scarcity, config),
        "consumption": consumption_multiplier(consumption, config),
        "pollution": pollution_multiplier(pollution, config) if user_type == "company" else 1.0,
    }
    unclamped = base
    for factor in factors.values():
        unclamped *= factor
    treatment_contribution = treatment_cost(treatment_intensity, config)
    unclamped += treatment_contribution
    final_price = min(ceiling, max(floor, unclamped))
    return {
        "price_per_m3": final_price,
        "unclamped_price_per_m3": unclamped,
        "floor": floor,
        "ceiling": ceiling,
        "decomposition": {
            "base_price": base,
            "multipliers": factors,
            "treatment_intensity_score": treatment_intensity,
            "treatment_cost_per_intensity_m3": config.treatment_cost_per_intensity_m3,
            "treatment_contribution_per_m3": treatment_contribution,
        },
        "explanation": (
            f"Treatment requirement contributed +€{treatment_contribution:.2f}/m³ to this scenario."
        ),
        "clamp": "floor" if unclamped < floor else "ceiling" if unclamped > ceiling else None,
    }


def optimize_revenue_target(inputs: Mapping[str, Any], config: PricingConfig | None = None) -> dict[str, Any]:
    """Find bounded prices for one household segment and one or more company segments.

    The result makes the trade-off visible: prices start at the scarcity/quality/
    pollution-informed recommendation, then revenue is fitted by moving company
    prices first and the household price last. This protects affordability while
    retaining the environmental signal wherever the target allows it.
    """
    config = config or PricingConfig()
    target = _nonnegative(inputs.get("desired_total_annual_revenue"), "desired_total_annual_revenue")
    household = dict(inputs.get("household", {}))
    household["user_type"] = "household"
    companies = [dict(item) for item in inputs.get("companies", [])]
    if not companies:
        raise ValueError("companies must contain at least one segment")
    household_demand = _nonnegative(household.get("annual_consumption_m3"), "household.annual_consumption_m3")
    household_users = _nonnegative(household.get("user_count", 1), "household.user_count")
    company_results = []
    for index, company in enumerate(companies):
        company["user_type"] = "company"
        result = calculate_price(company, config)
        demand = _nonnegative(company.get("annual_consumption_m3"), f"companies[{index}].annual_consumption_m3")
        users = _nonnegative(company.get("user_count", 1), f"companies[{index}].user_count")
        company_results.append({"name": company.get("name", f"Company {index + 1}"), "input": company,
                               "demand": demand * users, "price": result["price_per_m3"],
                               "recommended_price": result["price_per_m3"], "floor": result["floor"],
                               "ceiling": result["ceiling"], "pollution_score": company.get("pollution_score", 0)})
    h = calculate_price(household, config)
    household_price = h["price_per_m3"]
    household_floor, household_ceiling = h["floor"], h["ceiling"]
    def revenue(hp: float) -> float:
        return hp * household_demand * household_users + sum(c["price"] * c["demand"] for c in company_results)
    initial_revenue = revenue(household_price)
    # Fit with companies first, preserving pollution ordering and recommended signals.
    remaining = target - initial_revenue
    for c in sorted(company_results, key=lambda item: item["pollution_score"], reverse=True):
        if remaining > 0:
            change = min(remaining / c["demand"] if c["demand"] else 0, c["ceiling"] - c["price"])
        else:
            change = max(remaining / c["demand"] if c["demand"] else 0, c["floor"] - c["price"])
        c["price"] += change
        remaining -= change * c["demand"]
    # Only change household price if bounded company prices cannot meet the target.
    if abs(remaining) > 1e-9 and household_demand * household_users:
        household_price = min(household_ceiling, max(household_floor,
            household_price + remaining / (household_demand * household_users)))
        remaining = target - revenue(household_price)
    total = revenue(household_price)
    household_revenue = household_price * household_demand * household_users
    return {"household_price_per_m3": household_price,
            "company_prices": [{"name": c["name"], "price_per_m3": c["price"]} for c in company_results],
            "expected_total_annual_revenue": total, "target_revenue": target,
            "difference_from_target": total - target,
            "household_revenue_share": household_revenue / total if total else 0,
            "company_revenue_share": (total - household_revenue) / total if total else 0,
            "average_household_annual_bill": household_price * household_demand,
            "target_feasible": abs(total - target) < 1e-6,
            "trade_off": {"starting_revenue": initial_revenue, "household_price_changed": household_price != h["price_per_m3"],
                          "recommended_household_price": h["price_per_m3"],
                          "company_recommendations": [{"name": c["name"], "recommended_price_per_m3": c["recommended_price"],
                                                       "final_price_per_m3": c["price"], "pollution_score": c["pollution_score"]} for c in company_results]}}


def compare_scenarios(inputs: Mapping[str, Any], config: PricingConfig | None = None) -> dict[str, Any]:
    """Return side-by-side pricing, revenue, constraints, and chart data.

    ``household`` and ``company`` describe representative users. Each scenario
    may override any pricing input, especially ``scarcity_score`` and label.
    """
    config = config or PricingConfig()
    scenarios = inputs.get("scenarios")
    if not isinstance(scenarios, list) or len(scenarios) < 3:
        raise ValueError("scenarios must contain at least three scenarios")
    household = dict(inputs.get("household", {}))
    company = dict(inputs.get("company", {}))
    target = _nonnegative(inputs.get("desired_total_annual_revenue", 0), "desired_total_annual_revenue")

    def demand(item, name):
        return _nonnegative(item.get("annual_consumption_m3"), f"{name}.annual_consumption_m3") * _nonnegative(item.get("user_count", 1), f"{name}.user_count")

    household_demand, company_demand = demand(household, "household"), demand(company, "company")
    results = []
    for index, scenario in enumerate(scenarios):
        if not isinstance(scenario, Mapping):
            raise ValueError(f"scenarios[{index}] must be an object")
        h_input = {**household, **scenario, "user_type": "household"}
        c_input = {**company, **scenario, "user_type": "company"}
        h = calculate_price(h_input, config)
        c = calculate_price(c_input, config)
        pollution = _unit_interval(c_input.get("pollution_score", 0), "pollution_score")
        c_without_pollution = calculate_price({**c_input, "pollution_score": 0}, config)["price_per_m3"]
        revenue = h["price_per_m3"] * household_demand + c["price_per_m3"] * company_demand
        constraints = []
        if h["clamp"]:
            constraints.append(f"household_{h['clamp']}")
        if c["clamp"]:
            constraints.append(f"company_{c['clamp']}")
        if target and abs(revenue - target) < 1e-6:
            constraints.append("revenue_target")
        elif target and revenue < target:
            constraints.append("revenue_target_unmet")
        results.append({"name": scenario.get("name", f"Scenario {index + 1}"),
                        "scarcity_score": h_input["scarcity_score"],
                        "household_price_per_m3": h["price_per_m3"],
                        "company_price_per_m3": c["price_per_m3"],
                        "pollution_surcharge_per_m3": c["price_per_m3"] - c_without_pollution,
                        "expected_household_bill": h["price_per_m3"] * household_demand,
                        "expected_company_bill": c["price_per_m3"] * company_demand,
                        "total_utility_revenue": revenue,
                        "revenue_gap_vs_target": revenue - target if target else None,
                        "binding_constraints": constraints})

    chart = []
    for step in range(21):
        scarcity = step / 20
        h = calculate_price({**household, "user_type": "household", "scarcity_score": scarcity}, config)
        c = calculate_price({**company, "user_type": "company", "scarcity_score": scarcity}, config)
        chart.append({"scarcity_score": scarcity, "household_price_per_m3": h["price_per_m3"],
                      "company_price_per_m3": c["price_per_m3"],
                      "total_utility_revenue": h["price_per_m3"] * household_demand + c["price_per_m3"] * company_demand})
    return {"scenarios": results, "charts": {"scarcity_curve": chart},
            "chart_metadata": {"x": "scarcity_score", "series": ["household_price_per_m3", "company_price_per_m3", "total_utility_revenue"]},
            "target_revenue": target}
