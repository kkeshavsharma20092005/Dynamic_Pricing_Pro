import unittest

import numpy as np

from backend.engine import apply_log_smearing


class LogSmearingTests(unittest.TestCase):
    def test_apply_log_smearing_increases_prediction_with_residual_variance(self):
        log_pred = np.array([np.log(10.0)])
        adjusted = apply_log_smearing(log_pred, residual_variance=0.25)

        expected = np.expm1(np.log(10.0)) * np.exp(0.5 * 0.25)
        self.assertTrue(np.isclose(adjusted[0], expected))


if __name__ == "__main__":
    unittest.main()
