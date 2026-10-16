import pathlib
import unittest


class FrontendUiTests(unittest.TestCase):
    def test_indian_market_copy_is_present(self):
        html = pathlib.Path("frontend/index.html").read_text(encoding="utf-8")
        self.assertIn("Indian market", html)
        self.assertIn("festival", html.lower())


if __name__ == "__main__":
    unittest.main()
