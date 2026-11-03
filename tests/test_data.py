import sys
import unittest
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "data_pipeline"))

from config import RAW_CSV
from features import FEATURES, FORBIDDEN, chronological_split, load, parse_timestamps


class TimestampTests(unittest.TestCase):
    def test_iso_format_is_parsed(self):
        parsed = parse_timestamps(pd.Series(["2024-05-01 15:00:00"]))
        self.assertEqual(parsed[0], pd.Timestamp(2024, 5, 1, 15))

    def test_excel_format_is_read_day_first(self):
        parsed = parse_timestamps(pd.Series(["01-05-2024 15:00"]))
        self.assertEqual(parsed[0], pd.Timestamp(2024, 5, 1, 15))

    def test_unknown_format_is_rejected(self):
        with self.assertRaises(ValueError):
            parse_timestamps(pd.Series(["not a date"]))


class SplitTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.df = load(RAW_CSV)

    def test_rows_are_in_time_order(self):
        self.assertTrue(pd.api.types.is_datetime64_any_dtype(self.df.timestamp))
        self.assertTrue(self.df.timestamp.is_monotonic_increasing)

    def test_holdout_is_strictly_in_the_future(self):
        train, test = chronological_split(self.df)
        self.assertLess(train.timestamp.max(), test.timestamp.min())

    def test_answer_key_is_never_a_feature(self):
        self.assertFalse(set(FORBIDDEN) & set(FEATURES))


if __name__ == "__main__":
    unittest.main()
