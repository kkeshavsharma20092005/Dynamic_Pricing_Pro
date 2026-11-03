import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "data_pipeline"))

import testenv  # noqa: F401  (must precede the backend imports)
from fastapi.testclient import TestClient

from main import app

BASE = {
    "product_id": "JMU-CAB",
    "hour": 14, "day_of_week": 2, "month": 4,
    "temperature": 28.0, "precipitation": 0.0, "weather_condition": "Clear",
    "competitor_1_price": 220.0, "competitor_2_price": 231.0, "competitor_3_price": 213.0,
}


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.client = TestClient(app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)

    def predict(self, **override):
        response = self.client.post("/predict/", json={**BASE, **override})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()

    def test_health_and_metrics(self):
        self.assertEqual(self.client.get("/health/").status_code, 200)
        self.assertEqual(self.client.get("/metrics/").status_code, 200)

    def test_recommendation_respects_cost_and_guardrail(self):
        for hour in (3, 8, 14, 18):
            d = self.predict(hour=hour, max_change_pct=20)
            self.assertGreater(d["recommended_price"], d["unit_cost"])
            self.assertLessEqual(abs(d["price_change_pct"]), 20.01)

    def test_demand_falls_as_price_rises(self):
        demand = [p["demand"] for p in self.predict()["curve"]]
        self.assertEqual(demand, sorted(demand, reverse=True))

    def test_context_moves_the_price(self):
        night = self.predict(hour=3)["recommended_price"]
        rush = self.predict(hour=18)["recommended_price"]
        storm = self.predict(hour=18, precipitation=12.0,
                             weather_condition="Stormy")["recommended_price"]
        self.assertLess(night, rush)
        self.assertLess(rush, storm)

    def test_bad_input_is_rejected(self):
        cases = [
            ({"hour": 99}, 422),
            ({"current_price": -5}, 422),
            ({"product_id": "SKU-DOES-NOT-EXIST"}, 404),
            ({"current_price": 150, "unit_cost": 170}, 422),
            ({"precipitation": -3}, 422),
            ({"weather_condition": "Sunny"}, 422),
        ]
        for override, expected in cases:
            with self.subTest(override=override):
                response = self.client.post("/predict/", json={**BASE, **override})
                self.assertEqual(response.status_code, expected)


if __name__ == "__main__":
    unittest.main()
