import json
import unittest

from career_agent.evals import QUESTIONS_PATH, first_relevant_rank, summarize


class RetrievalEvalTests(unittest.TestCase):
    def test_rank_is_the_first_accepted_source(self):
        self.assertEqual(first_relevant_rank(["data/a.md", "data/b.md", "data/c.md"], {"data/c.md", "data/b.md"}), 2)
        self.assertIsNone(first_relevant_rank(["data/a.md"], {"data/z.md"}))

    def test_summary_counts_misses_as_zero(self):
        self.assertEqual(summarize([1, 2, None, 4]), (0.25, (1 + 0.5 + 0.25) / 4))

    def test_question_sources_exist(self):
        project_root = QUESTIONS_PATH.parents[1]
        for case in json.loads(QUESTIONS_PATH.read_text(encoding="utf-8")):
            for source in case["sources"]:
                self.assertTrue((project_root / source).is_file(), source)


if __name__ == "__main__":
    unittest.main()
