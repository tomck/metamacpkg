"""Importer safety: only well-formed proposals reach pending.yaml,
which the build never trusts."""
import unittest

from metamacpkg import issues as I


def body(proposal_json):
    return ("Review-site verdict\n\n- pair: x\n\n"
            f"<!-- metamacpkg-proposal {proposal_json} -->")


class TestParseBody(unittest.TestCase):
    def test_confirm(self):
        p = I.parse_body(body('{"pair": "a-to-b", "source": "s", '
                              '"decision": "confirm", "target": "t"}'))
        self.assertEqual((p["decision"], p["target"]), ("confirm", "t"))

    def test_no_equivalent_needs_no_target(self):
        p = I.parse_body(body('{"pair": "a-to-b", "source": "s", '
                              '"decision": "no-equivalent"}'))
        self.assertEqual(p["decision"], "no-equivalent")

    def test_missing_block(self):
        self.assertIsNone(I.parse_body("just some text"))

    def test_bad_json(self):
        self.assertIsNone(I.parse_body("<!-- metamacpkg-proposal {oops} -->"))

    def test_bad_decision(self):
        self.assertIsNone(I.parse_body(
            body('{"pair": "a", "source": "s", "decision": "yes"}')))

    def test_confirm_requires_target(self):
        self.assertIsNone(I.parse_body(
            body('{"pair": "a", "source": "s", "decision": "confirm"}')))

    def test_missing_source(self):
        self.assertIsNone(I.parse_body(
            body('{"pair": "a", "decision": "confirm", "target": "t"}')))


class TestPending(unittest.TestCase):
    def test_append_and_dedupe(self):
        import tempfile
        from pathlib import Path
        tmp = tempfile.TemporaryDirectory()
        old = I.PENDING
        I.PENDING = Path(tmp.name) / "pending.yaml"
        try:
            I.append_pending([{"issue": 7, "imported_at": "t",
                               "author": 'a"b', "pair": "p", "source": "s",
                               "decision": "confirm", "target": "x",
                               "comment": "c:d"}])
            self.assertEqual(I.already_imported(), {7})
            text = I.PENDING.read_text()
            self.assertIn('author: "a\\"b"', text)
        finally:
            I.PENDING = old
            tmp.cleanup()


if __name__ == "__main__":
    unittest.main()
