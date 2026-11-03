import unittest

import numpy as np

from backend.engine import PricingEngine, apply_log_smearing


class LagTableTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.lags = PricingEngine().lags

    def test_lags_follow_the_scenario(self):
        wednesday = 2 * 24
        night = self.lags[("JMU-CAB", wednesday + 3)]
        evening = self.lags[("JMU-CAB", wednesday + 19)]
        self.assertLess(night["demand_lag_1h"], evening["demand_lag_1h"])

    def test_one_hour_and_24_hour_lags_are_different_values(self):
        lag = self.lags[("JMU-CAB", 2 * 24 + 18)]
        self.assertNotEqual(lag["demand_lag_1h"], lag["demand_lag_24h"])

    def test_monday_midnight_looks_back_to_the_weekend(self):
        monday_midnight = self.lags[("JMU-CAB", 0)]
        tuesday_midnight = self.lags[("JMU-CAB", 24)]
        self.assertNotEqual(monday_midnight["demand_lag_24h"],
                            tuesday_midnight["demand_lag_24h"])


class LogSmearingTests(unittest.TestCase):
    def test_apply_log_smearing_increases_prediction_with_residual_variance(self):
        log_pred = np.array([np.log(10.0)])
        adjusted = apply_log_smearing(log_pred, residual_variance=0.25)

        expected = np.expm1(np.log(10.0)) * np.exp(0.5 * 0.25)
        self.assertTrue(np.isclose(adjusted[0], expected))


if __name__ == "__main__":
    unittest.main()
