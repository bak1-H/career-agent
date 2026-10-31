import unittest
from unittest.mock import Mock


from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from career_agent.graph import EVIDENCE_LIMIT, PROMPT_CHAR_BUDGET, create_agent, select_excerpt
from career_agent.retrieval import DocumentationIndexer, DocumentationRetriever


class LightweightAgentTests(unittest.TestCase):
    def test_one_generation_with_bounded_evidence_and_callbacks(self):
        calls = []
        def generate(messages, config):
            calls.append((messages, config))
            return AIMessage(content="Respuesta final.", response_metadata={"eval_count": 12})
        model = RunnableLambda(generate)
        retriever = Mock()
        retriever.search.return_value = [Document(page_content="Python " * 10000, metadata={"source": f"data/{i}.md"}) for i in range(3)]
        agent = create_agent(retriever, model)
        result = agent.invoke({"messages": [HumanMessage(content="Python?")]}, config={"metadata": {"marker": "passed"}})
        self.assertEqual(result["messages"][-1].content, "Respuesta final.")
        self.assertEqual(result["messages"][-1].response_metadata["eval_count"], 12)
        self.assertEqual(len(calls), 1)
        messages, config = calls[0]
        self.assertEqual(config["metadata"]["marker"], "passed")
        self.assertIsNotNone(config["callbacks"])
        self.assertEqual(len(messages), 2)
        self.assertLess(sum(len(message.content) for message in messages), PROMPT_CHAR_BUDGET)
        self.assertIn("Fuente: data/0.md", messages[1].content)
        self.assertIn("Fuente: data/1.md", messages[1].content)
        self.assertIn("Fuente: data/2.md", messages[1].content)
        self.assertIn("Evidencia:\n", messages[1].content)
        self.assertTrue(messages[1].content.endswith("Pregunta:\nPython?"))
        retriever.search.assert_called_once_with("Python?", limit=EVIDENCE_LIMIT)

    def test_model_response_is_returned_with_its_usage(self):
        response = AIMessage(
            content="Respuesta final.",
            usage_metadata={"input_tokens": 10, "output_tokens": 25, "total_tokens": 35},
        )
        retriever = Mock()
        retriever.search.return_value = []
        result = create_agent(retriever, RunnableLambda(lambda messages: response)).invoke({"messages": [HumanMessage(content="Pregunta")]})
        self.assertEqual(result["messages"][-1], response)

    def test_relevant_late_paragraph_is_retained(self):
        text = "Unrelated " * 1000 + "\n\nPython evidence near the end."
        self.assertIn("Python evidence", select_excerpt(text, "Python", 100))

    def test_followup_retains_bounded_user_context_without_reusing_assistant_facts(self):
        calls = []
        def generate(messages, config):
            calls.append(messages)
            return AIMessage(content="Grounded answer")
        retriever = Mock()
        retriever.search.return_value = [Document(page_content="Current source", metadata={"source": "data/project.md"})]
        agent = create_agent(retriever, RunnableLambda(generate))
        result = agent.invoke({"messages": [
            HumanMessage(content="Old unrelated topic"),
            AIMessage(content="Old answer"),
            HumanMessage(content="What does Control de Activos solve?" + " context" * 1000),
            AIMessage(content="Unverified assistant assertion"),
            HumanMessage(content="And which technologies does it use?"),
        ]})
        self.assertEqual(len(calls), 1)
        query = retriever.search.call_args.args[0]
        self.assertTrue(query.startswith("And which technologies does it use?"))
        self.assertIn("Control de Activos", query)
        self.assertLess(len(query), 600)
        prompt = calls[0][1].content
        self.assertIn("Control de Activos", prompt)
        self.assertIn("la pregunta actual tiene prioridad", prompt)
        self.assertNotIn("Unverified assistant assertion", prompt)
        self.assertNotIn("Old unrelated topic", prompt)
        self.assertEqual(result["messages"][-1].content, "Grounded answer")

    def test_oversized_question_is_rejected_without_retrieval_or_generation(self):
        retriever = Mock()
        model = Mock()
        agent = create_agent(retriever, model)
        with self.assertRaisesRegex(ValueError, "context budget"):
            agent.invoke({"messages": [HumanMessage(content="x" * PROMPT_CHAR_BUDGET)]})
        retriever.search.assert_not_called()
        model.invoke.assert_not_called()

    def test_indexing_adds_only_missing_or_changed_chunks_and_is_repeatable(self):
        source = Mock()
        splitter = Mock()
        index = Mock()
        existing = Document(page_content="existing", metadata={"source": "data/a.md"})
        changed = Document(page_content="changed", metadata={"source": "data/b.md"})
        source.load.return_value = [existing, changed]
        splitter.split.return_value = [existing, changed]
        index.contains.side_effect = [True, False, True, True]
        index.remove_stale.return_value = 0
        indexer = DocumentationIndexer(source, splitter, index)
        first = indexer.ensure_indexed()
        second = indexer.ensure_indexed()
        index.add_documents.assert_called_once_with([changed])
        self.assertEqual(first.chunk_count, 1)
        self.assertTrue(first.indexed)
        self.assertFalse(second.indexed)
        self.assertEqual(index.contains.call_args.args, ("data/b.md", "changed"))
        self.assertEqual(index.ensure_ready.call_count, 2)

    def test_stale_semantic_versions_are_excluded_for_local_sources(self):
        current = Document(page_content="Python current", metadata={"source": "data/a.md"})
        stale = Document(page_content="Python stale", metadata={"source": "data/a.md"})
        external = Document(page_content="Other", metadata={"source": "external"})
        index = Mock()
        index.similarity_search.return_value = [stale, external]
        self.assertEqual(DocumentationRetriever(index, [current]).search("Python"), [current, external])


if __name__ == "__main__":
    unittest.main()
