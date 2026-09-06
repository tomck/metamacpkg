"""Triage rules: maintainer auto-accept, community votes, dupes, conflicts."""
import unittest

from metamacpkg.triage import evaluate


class TestEvaluate(unittest.TestCase):
    def test_maintainer_author_accepts(self):
        v, _ = evaluate(author="tomck", maintainer="tomck", voters=set(),
                        proposal_exists=None)
        self.assertEqual(v, "accept")

    def test_maintainer_vote_accepts(self):
        v, _ = evaluate(author=" stranger ".strip(), maintainer="tomck",
                        voters={"tomck"}, proposal_exists=None)
        self.assertEqual(v, "accept")

    def test_two_community_votes_accept(self):
        v, _ = evaluate(author="a", maintainer="tomck", voters={"b", "c"},
                        proposal_exists=None)
        self.assertEqual(v, "accept")

    def test_one_vote_waits(self):
        v, reason = evaluate(author="a", maintainer="tomck", voters={"b"},
                             proposal_exists=None)
        self.assertEqual(v, "wait")
        self.assertIn("1/2", reason)

    def test_author_self_vote_does_not_count(self):
        v, _ = evaluate(author="a", maintainer="tomck", voters={"a"},
                        proposal_exists=None)
        self.assertEqual(v, "wait")

    def test_existing_proposal_is_duplicate(self):
        v, _ = evaluate(author="tomck", maintainer="tomck", voters=set(),
                        proposal_exists=("relation", "gtk3"))
        self.assertEqual(v, "duplicate")


if __name__ == "__main__":
    unittest.main()
