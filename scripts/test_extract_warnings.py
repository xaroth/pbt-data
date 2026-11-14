import contextlib
import io
import tempfile
import unittest
from pathlib import Path

import extract_warnings

LOG = """\
some other line
pbt-extract: warning: override AscendancyTrickster6: the buffs of passive Heartstopper are not carried
pbt-extract: warning: override AscendancySlayer8: the buffs of passive Overwhelm are not carried
pbt-extract: warning: table Mods: 545 mods of domain 38 left out; no kept base has that domain
pbt-extract: warning: a warning added by hand
"""


class SummaryTest(unittest.TestCase):
    def test_counts_warnings_by_kind(self):
        out = extract_warnings.summary("3.29", extract_warnings.parse(LOG))
        self.assertIn("### 3.29: 4 warnings", out)
        self.assertIn("| 2 | override …: the buffs of passive … are not carried |", out)
        self.assertIn("| 1 | table Mods: 545 mods of domain 38 left out; no kept base has that domain |", out)
        self.assertIn("| 1 | a warning added by hand |", out)
        self.assertIn("override AscendancySlayer8: the buffs of passive Overwhelm are not carried\n", out)
        self.assertNotIn("some other line", out)

    def test_no_warnings(self):
        self.assertEqual(extract_warnings.summary("3.30", []), "### 3.30: no warnings\n")

    def test_kind_replaces_each_item(self):
        self.assertEqual(
            extract_warnings.kind('override runegraft_12: named "[DNT - UNUSED] Grafted", unused; left out'),
            "override …: named …, unused; left out",
        )
        self.assertEqual(
            extract_warnings.kind("override vaal_pact1: stat row 812 repeated; left out"),
            "override …: stat row … repeated; left out",
        )

    def test_cell_escapes_pipe(self):
        out = extract_warnings.summary("x", ["a | b"])
        self.assertIn("| 1 | a \\| b |", out)


class MainTest(unittest.TestCase):
    def test_no_log_writes_nothing(self):
        out = io.StringIO()
        with tempfile.TemporaryDirectory() as d, contextlib.redirect_stdout(out):
            self.assertEqual(extract_warnings.main(["x", "3.29", str(Path(d) / "none.log")]), 0)
        self.assertEqual(out.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
