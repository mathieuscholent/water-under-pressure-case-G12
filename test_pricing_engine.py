import unittest

from pricing_engine import (PricingConfig, calculate_price, model_assumptions,
                            compare_scenarios, optimize_revenue_target, reset_to_defaults,
                            wei_to_scarcity_score)


BASE = {
    "annual_consumption_m3": 100,
    "scarcity_score": 0.2,
    "treatment_intensity_score": 0,
    "pollution_score": 0,
    "household_price_floor": 1,
    "household_price_ceiling": 10,
    "company_price_floor": 1,
    "company_price_ceiling": 20,
    "base_household_price": 2,
    "base_company_price": 3,
}


class PricingEngineTests(unittest.TestCase):
    def price(self, user_type="household", **changes):
        values = {**BASE, "user_type": user_type, **changes}
        return calculate_price(values)

    def test_monotonic_factors(self):
        self.assertGreater(self.price(scarcity_score=1)["price_per_m3"], self.price(scarcity_score=0)["price_per_m3"])
        self.assertGreater(self.price(treatment_intensity_score=1)["price_per_m3"], self.price(treatment_intensity_score=0)["price_per_m3"])
        self.assertGreater(self.price("company", pollution_score=1)["price_per_m3"], self.price("company", pollution_score=0)["price_per_m3"])

    def test_households_never_get_pollution_multiplier(self):
        result = self.price(pollution_score=1)
        self.assertEqual(result["decomposition"]["multipliers"]["pollution"], 1.0)

    def test_treatment_cost_is_transparent_and_additive(self):
        result = self.price(treatment_intensity_score=0.5)
        self.assertEqual(result["decomposition"]["treatment_contribution_per_m3"], 0.2)
        self.assertIn("+€0.20/m³", result["explanation"])

    def test_legacy_quality_input_is_not_accepted(self):
        with self.assertRaises(ValueError):
            self.price(water_quality_score=0.2)

    def test_clamps_to_applicable_bounds(self):
        result = self.price(base_household_price=100)
        self.assertEqual(result["price_per_m3"], 10)
        self.assertEqual(result["clamp"], "ceiling")

    def test_invalid_input_rejected(self):
        with self.assertRaises(ValueError):
            self.price(scarcity_score=1.1)
        with self.assertRaises(ValueError):
            self.price(household_price_floor=11)

    def test_revenue_target_reports_shares_and_feasibility(self):
        result = optimize_revenue_target({"desired_total_annual_revenue": 950,
            "household": {**BASE, "annual_consumption_m3": 100, "user_count": 2},
            "companies": [{**BASE, "annual_consumption_m3": 100, "user_count": 1, "pollution_score": 1}]})
        self.assertTrue(result["target_feasible"])
        self.assertAlmostEqual(result["household_revenue_share"] + result["company_revenue_share"], 1)
        self.assertEqual(result["average_household_annual_bill"], result["household_price_per_m3"] * 100)

    def test_revenue_target_can_be_infeasible(self):
        result = optimize_revenue_target({"desired_total_annual_revenue": 99999,
            "household": {**BASE, "user_count": 1}, "companies": [{**BASE, "user_count": 1}]})
        self.assertFalse(result["target_feasible"])

    def test_wei_normalization_is_separate_from_raw_value(self):
        self.assertEqual(wei_to_scarcity_score(20), 0.5)
        self.assertEqual(wei_to_scarcity_score(55), 1.0)

    def test_scenario_comparison_has_metrics_constraints_and_chart(self):
        common = {**BASE, "annual_consumption_m3": 100}
        result = compare_scenarios({"desired_total_annual_revenue": 5000,
            "household": {**common, "user_count": 2},
            "company": {**common, "user_type": "company", "user_count": 1, "pollution_score": 1},
            "scenarios": [{"name": "Normal year", "scarcity_score": 0.2},
                          {"name": "Dry year", "scarcity_score": 0.6},
                          {"name": "Severe drought", "scarcity_score": 0.9}]})
        self.assertEqual([s["name"] for s in result["scenarios"]], ["Normal year", "Dry year", "Severe drought"])
        self.assertIn("pollution_surcharge_per_m3", result["scenarios"][0])
        self.assertIn("revenue_target_unmet", result["scenarios"][0]["binding_constraints"])
        self.assertEqual(len(result["charts"]["scarcity_curve"]), 21)
        self.assertEqual(result["charts"]["scarcity_curve"][0]["scarcity_score"], 0)
        self.assertEqual(result["charts"]["scarcity_curve"][-1]["scarcity_score"], 1)
        self.assertGreater(result["scenarios"][-1]["household_price_per_m3"], result["scenarios"][0]["household_price_per_m3"])

    def test_scenario_comparison_requires_three_scenarios(self):
        with self.assertRaises(ValueError):
            compare_scenarios({"household": BASE, "company": BASE, "scenarios": [{"scarcity_score": 0}]})
    def test_zero_consumption_still_calculates_a_bounded_unit_price(self):
        # Economically, a zero-volume customer should have a valid tariff, but no bill.
        result = self.price(annual_consumption_m3=0)
        self.assertAlmostEqual(result["price_per_m3"], 2.2)

    def test_extremely_high_consumption_saturates_the_volume_signal(self):
        # Economically, the volume adjustment is capped at its reference level.
        result = self.price(annual_consumption_m3=10**12)
        self.assertAlmostEqual(result["price_per_m3"], 2.64)

    def test_scarcity_boundaries(self):
        # Economically, no scarcity has no premium; maximum scarcity has the full premium.
        self.assertAlmostEqual(self.price(scarcity_score=0)["price_per_m3"], 2.2)
        self.assertAlmostEqual(self.price(scarcity_score=1)["price_per_m3"], 3.3)

    def test_pollution_boundaries_apply_only_to_companies(self):
        # Economically, pollution should raise a company's price, while households have no pollution premium.
        self.assertAlmostEqual(self.price("company", pollution_score=0)["price_per_m3"], 3.63)
        self.assertAlmostEqual(self.price("company", pollution_score=1)["price_per_m3"], 5.808)
        self.assertAlmostEqual(self.price(pollution_score=1)["price_per_m3"], 2.42)

    def test_equal_floor_and_ceiling_is_a_fixed_price(self):
        # Economically, a zero-width tariff band leaves no pricing discretion.
        result = self.price(household_price_floor=4, household_price_ceiling=4)
        self.assertEqual(result["price_per_m3"], 4)

    def test_floor_above_ceiling_is_rejected(self):
        # Economically, an inverted tariff band is incoherent and must not be priced.
        with self.assertRaises(ValueError):
            self.price(household_price_floor=11, household_price_ceiling=10)

    def test_negative_consumption_is_rejected(self):
        # Economically, negative demand is impossible rather than a discount.
        with self.assertRaises(ValueError):
            self.price(annual_consumption_m3=-1)

    def test_missing_water_quality_data_is_rejected(self):
        # Economically, a missing treatment requirement cannot silently become a quality assumption.
        values = {key: value for key, value in BASE.items() if key != "treatment_intensity_score"}
        with self.assertRaises(ValueError):
            calculate_price({**values, "user_type": "household"})

    def test_unavailable_external_api_is_reported(self):
        # Economically, unavailable public data should fail clearly, never invent scarcity.
        from unittest.mock import patch
        with patch("pricing_engine.urlopen", side_effect=OSError("service unavailable")):
            with self.assertRaises(OSError):
                from pricing_engine import fetch_eea_scarcity
                fetch_eea_scarcity("Germany")

    def _revenue_case(self, target):
        return optimize_revenue_target({
            "desired_total_annual_revenue": target,
            "household": {**BASE, "annual_consumption_m3": 100, "user_count": 1},
            "companies": [{**BASE, "annual_consumption_m3": 100, "user_count": 1}],
        })

    def test_target_below_minimum_is_bounded_at_floors(self):
        # Economically, revenue cannot fall below all segment floors.
        result = self._revenue_case(1)
        self.assertFalse(result["target_feasible"])
        self.assertAlmostEqual(result["expected_total_annual_revenue"], 200)

    def test_target_above_maximum_is_bounded_at_ceilings(self):
        # Economically, revenue cannot exceed all segment ceilings.
        result = self._revenue_case(10**9)
        self.assertFalse(result["target_feasible"])
        self.assertAlmostEqual(result["expected_total_annual_revenue"], 3000)

    def test_exactly_achievable_target_is_reported_feasible(self):
        # Economically, an attainable target should be met without residual error.
        result = self._revenue_case(525)
        self.assertTrue(result["target_feasible"])
        self.assertAlmostEqual(result["expected_total_annual_revenue"], 525)

    def test_company_ceiling_can_be_reached_by_pollution(self):
        # Economically, pollution raises the recommendation, but the contractual ceiling remains binding.
        result = self.price("company", pollution_score=1, base_company_price=100)
        self.assertEqual(result["price_per_m3"], 20)
        self.assertEqual(result["clamp"], "ceiling")

    def test_household_ceiling_can_be_reached_by_scarcity(self):
        # Economically, scarcity can push a household tariff to its affordability ceiling.
        result = self.price(scarcity_score=1, base_household_price=100)
        self.assertEqual(result["price_per_m3"], 10)
        self.assertEqual(result["clamp"], "ceiling")

    def test_model_assumptions_panel_classifies_inputs_and_sources_real_data(self):
        # Economically, observed scarcity must remain distinguishable from user-entered and assumed values.
        panel = model_assumptions(BASE)
        sections = {section["name"]: section["items"] for section in panel["sections"]}
        self.assertEqual({item["name"] for item in sections["REAL DATA"]}, {"scarcity_score"})
        self.assertIn("European Environment Agency", sections["REAL DATA"][0]["source"])
        self.assertIn("annual_consumption_m3", {item["name"] for item in sections["USER INPUT"]})
        assumption_names = {item["name"] for item in sections["MODEL ASSUMPTION"]}
        self.assertIn("optimization priorities", assumption_names)
        self.assertNotIn("observed", " ".join(item["source"] for item in sections["MODEL ASSUMPTION"]).lower())

    def test_reset_to_defaults_returns_default_pricing_configuration(self):
        # Economically, reset must restore the documented baseline rather than retain a prior override.
        self.assertEqual(reset_to_defaults(), PricingConfig())


if __name__ == "__main__":
    unittest.main()
