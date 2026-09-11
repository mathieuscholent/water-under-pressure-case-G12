import unittest

from pricing_engine import PricingConfig, calculate_price


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


if __name__ == "__main__":
    unittest.main()
