import unittest


from langchain_core.documents import Document

from career_agent.retrieval import DocumentationRetriever


def document(text, source="profile.md"):
    return Document(page_content=text, metadata={"source": source})


class FakeIndex:
    def __init__(self, documents=(), error=None):
        self.documents = list(documents)
        self.error = error
        self.calls = []

    def similarity_search(self, query, k):
        self.calls.append((query, k))
        if self.error:
            raise self.error
        return self.documents[:k]


class HybridRetrievalTests(unittest.TestCase):
    def test_lexical_hit_does_not_skip_semantic_search(self):
        lexical = document("Python development")
        semantic = document("Software engineering")
        index = FakeIndex([semantic])

        result = DocumentationRetriever(index, [lexical]).search("Python", limit=2)

        self.assertEqual(result, [lexical, semantic])
        self.assertEqual(index.calls, [("Python", 8)])

    def test_consensus_outweighs_each_channels_first_result(self):
        lexical = document("Python")
        consensus = document("Python engineering")
        semantic = document("Backend architecture")
        index = FakeIndex([semantic, consensus])

        result = DocumentationRetriever(index, [lexical, consensus]).search("Python")

        self.assertEqual(result, [consensus, lexical, semantic])

    def test_duplicates_do_not_inflate_score_or_consume_lexical_candidates(self):
        first = document("Python", "first.md")
        consensus = document("Python engineering", "second.md")
        duplicate = document("Python", "first.md")
        duplicate.metadata["mongo_id"] = "another-copy"
        index = FakeIndex([first, duplicate, consensus])

        result = DocumentationRetriever(index, [first] * 8 + [consensus]).search(
            "Python", limit=1
        )
        baseline = DocumentationRetriever(FakeIndex([first, consensus]), [first, consensus])

        self.assertEqual(result, baseline.search("Python", limit=1))
        self.assertEqual(len(result), 1)

    def test_semantic_duplicates_do_not_penalize_later_unique_ranks(self):
        first = document("Architecture")
        consensus = document("Python engineering")
        lexical = document("Python")
        index = FakeIndex([first, first, first, consensus])

        result = DocumentationRetriever(index, [lexical, consensus]).search("Python")

        self.assertEqual(result, [consensus, lexical, first])

    def test_same_text_from_different_sources_retains_attribution(self):
        first = document("Python", "first.md")
        second = document("Python", "second.md")

        result = DocumentationRetriever(FakeIndex([first, second]), [first]).search("Python")

        self.assertEqual(result, [first, second])

    def test_invalid_queries_and_limits_do_not_call_index(self):
        index = FakeIndex()
        retriever = DocumentationRetriever(index)

        for query, limit in [("", 4), ("  ", 4), ("?!", 4), ("de la", 4), ("Python", 0), ("Python", -1)]:
            with self.subTest(query=query, limit=limit):
                self.assertEqual(retriever.search(query, limit), [])
        self.assertEqual(index.calls, [])

    def test_each_channel_can_supply_results_alone(self):
        lexical = document("Python")
        semantic = document("Architecture")

        self.assertEqual(DocumentationRetriever(FakeIndex(), [lexical]).search("Python"), [lexical])
        self.assertEqual(DocumentationRetriever(FakeIndex([semantic])).search("Python"), [semantic])
        self.assertEqual(DocumentationRetriever(FakeIndex()).search("Python"), [])

    def test_limit_and_ties_are_deterministic(self):
        lexical = [document("Python", f"lexical-{position}.md") for position in range(4)]
        semantic = [document("Architecture", f"semantic-{position}.md") for position in range(4)]
        retriever = DocumentationRetriever(FakeIndex(semantic), lexical)

        for _ in range(3):
            self.assertEqual(retriever.search("Python", limit=3), [lexical[0], semantic[0], lexical[1]])

    def test_semantic_errors_propagate_even_with_lexical_hits(self):
        retriever = DocumentationRetriever(FakeIndex(error=RuntimeError("offline")), [document("Python")])

        with self.assertRaisesRegex(RuntimeError, "offline"):
            retriever.search("Python")


if __name__ == "__main__":
    unittest.main()
