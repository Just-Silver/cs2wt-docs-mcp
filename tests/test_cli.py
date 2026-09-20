import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from cs2wt.cli import _build_parser, main
from cs2wt.index import DocIndex


class CliTest(unittest.TestCase):
    def test_no_api_option(self):
        with self.assertRaises(SystemExit):
            _build_parser().parse_args(["--api", "x", "status"])

    def test_list_prints_titles(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "docs.sqlite"
            index = DocIndex(db)
            index.upsert(title="Alpha", content="a", revid=1, timestamp="t", url="u")
            index.commit()
            index.close()

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--db", str(db), "list"])
            self.assertEqual(code, 0)
            self.assertEqual(out.getvalue().strip(), "Alpha")

    def test_get_by_title(self):
        with tempfile.TemporaryDirectory() as d:
            db = Path(d) / "docs.sqlite"
            index = DocIndex(db)
            index.upsert(title="Alpha", content="hello body", revid=1, timestamp="t", url="u")
            index.commit()
            index.close()

            out = io.StringIO()
            with redirect_stdout(out):
                code = main(["--db", str(db), "get", "Alpha"])
            self.assertEqual(code, 0)
            self.assertIn("hello body", out.getvalue())


if __name__ == "__main__":
    unittest.main()