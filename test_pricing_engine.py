import unittest

from pricing_engine import PricingConfig, calculate_price, optimize_revenue_target


BASE = {
    "annual_consumption_m3": 100,
    "scarcity_score": 0.2,
    "water_quality_score": 1,
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
        self.assertGreater(self.price(water_quality_score=0)["price_per_m3"], self.price(water_quality_score=1)["price_per_m3"])
        self.assertGreater(self.price("company", pollution_score=1)["price_per_m3"], self.price("company", pollution_score=0)["price_per_m3"])

    def test_households_never_get_pollution_multiplier(self):
        result = self.price(pollution_score=1)
        self.assertEqual(result["decomposition"]["multipliers"]["pollution"], 1.0)

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


if __name__ == "__main__":
    unittest.main()
