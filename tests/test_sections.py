import unittest

from cs2wt.sections import extract_section

MD = """# Title

intro

## Alpha

alpha body

### Alpha Sub

sub body

## Beta

beta body
"""


class ExtractSectionTest(unittest.TestCase):
    def test_exact_heading_includes_subsections(self):
        out = extract_section(MD, "Alpha")
        self.assertIsNotNone(out)
        self.assertIn("alpha body", out)
        self.assertIn("### Alpha Sub", out)
        self.assertNotIn("beta body", out)

    def test_case_and_whitespace_insensitive(self):
        self.assertIsNotNone(extract_section(MD, "  beta "))

    def test_substring_match_fallback(self):
        self.assertIsNotNone(extract_section(MD, "Alph"))

    def test_missing_returns_none(self):
        self.assertIsNone(extract_section(MD, "Gamma"))

    def test_same_level_boundary(self):
        out = extract_section(MD, "Beta")
        self.assertIsNotNone(out)
        self.assertNotIn("alpha body", out)


if __name__ == "__main__":
    unittest.main()