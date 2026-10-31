import unittest
from unittest.mock import Mock, patch


from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from career_agent.config import Settings
from career_agent.graph import create_agent, select_excerpt
from career_agent.retrieval import DocumentationIndexer, DocumentationRetriever


def settings(**overrides):
    values = dict(ollama_base_url="http://unused", ollama_chat_model="qwen3:4b", ollama_embedding_model="unused", mongodb_uri="unused", mongodb_database="unused", mongodb_collection="unused", atlas_vector_search_index_name="unused")
    return Settings(**(values | overrides))


class LightweightAgentTests(unittest.TestCase):
    def test_one_generation_with_bounded_evidence_and_callbacks(self):
        calls = []
        def generate(messages, config):
            calls.append((messages, config))
            return AIMessage(content="Respuesta final.\nFuente: data/0.md", response_metadata={"eval_count": 12})
        model = RunnableLambda(generate)
        retriever = Mock()
        retriever.search.return_value = [Document(page_content="Python " * 10000, metadata={"source": f"data/{i}.md"}) for i in range(3)]
        with patch("career_agent.graph.ChatOllama", return_value=model) as constructor:
            agent = create_agent(settings(), retriever)
            result = agent.invoke({"messages": [HumanMessage(content="Python?")]}, config={"metadata": {"marker": "passed"}})
        self.assertEqual(result["messages"][-1].content, "Respuesta final.\nFuente: data/0.md")
        self.assertEqual(result["messages"][-1].response_metadata["eval_count"], 12)
        self.assertEqual(len(calls), 1)
        messages, config = calls[0]
        self.assertEqual(config["metadata"]["marker"], "passed")
        self.assertIsNotNone(config["callbacks"])
        self.assertIsInstance(messages[-1], AIMessage)
        self.assertEqual(messages[-1].content, "<think>\n</think>\n\n")
        self.assertLess(sum(len(message.content) for message in messages), 3500)
        self.assertIn("Fuente: data/0.md", messages[1].content)
        self.assertIn("Fuente: data/1.md", messages[1].content)
        self.assertIn("Fuente: data/2.md", messages[1].content)
        self.assertTrue(messages[1].content.endswith("/no_think"))
        self.assertIn("Evidencia:\n", messages[1].content)
        self.assertIn("Pregunta:\nPython?", messages[1].content)
        retriever.search.assert_called_once_with("Python?", limit=3)
        self.assertEqual(constructor.call_args.kwargs["num_ctx"], 4096)
        self.assertEqual(constructor.call_args.kwargs["num_predict"], 384)
        self.assertEqual(constructor.call_args.kwargs["keep_alive"], "10m")
        self.assertFalse(constructor.call_args.kwargs["reasoning"])

    def test_qwen_protocol_reasoning_is_removed_without_losing_usage(self):
        response = AIMessage(
            content="Reasoning</think>\nRespuesta final.\nFuente: data/project.md",
            response_metadata={"eval_count": 25},
            usage_metadata={"input_tokens": 10, "output_tokens": 25, "total_tokens": 35},
        )
        retriever = Mock()
        retriever.search.return_value = []
        with patch("career_agent.graph.ChatOllama", return_value=RunnableLambda(lambda messages: response)):
            result = create_agent(settings(), retriever).invoke({"messages": [HumanMessage(content="Pregunta")]})
        final = result["messages"][-1]
        self.assertEqual(final.content, "Respuesta final.\nFuente: data/project.md")
        self.assertEqual(final.response_metadata, response.response_metadata)
        self.assertEqual(final.usage_metadata, response.usage_metadata)

    def test_incomplete_qwen_thinking_does_not_become_a_final_answer(self):
        for content in ["<think>Unfinished reasoning", "Reasoning</think>\n", "Reasoning</think>\n<think>unfinished"]:
            with self.subTest(content=content):
                retriever = Mock()
                retriever.search.return_value = []
                response = AIMessage(content=content)
                with patch("career_agent.graph.ChatOllama", return_value=RunnableLambda(lambda messages: response)):
                    with self.assertRaisesRegex(RuntimeError, "final response"):
                        create_agent(settings(), retriever).invoke({"messages": [HumanMessage(content="Pregunta")]})

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
        with patch("career_agent.graph.ChatOllama", return_value=RunnableLambda(generate)):
            agent = create_agent(settings(), retriever)
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
        with patch("career_agent.graph.ChatOllama", return_value=model):
            agent = create_agent(settings(), retriever)
            with self.assertRaisesRegex(ValueError, "context budget"):
                agent.invoke({"messages": [HumanMessage(content="x" * 5000)]})
        retriever.search.assert_not_called()
        model.invoke.assert_not_called()

    def test_invalid_generation_limits_are_rejected(self):
        for overrides in [dict(ollama_num_ctx=1024), dict(ollama_num_predict=0), dict(ollama_num_predict=3000)]:
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                settings(**overrides)

    def test_indexing_adds_only_missing_or_changed_chunks_and_is_repeatable(self):
        source = Mock()
        splitter = Mock()
        index = Mock()
        existing = Document(page_content="existing", metadata={"source": "data/a.md"})
        changed = Document(page_content="changed", metadata={"source": "data/b.md"})
        source.load.return_value = [existing, changed]
        splitter.split.return_value = [existing, changed]
        collection = Mock()
        collection.count_documents.side_effect = [1, 0, 1, 1]
        indexer = DocumentationIndexer(source, splitter, index, collection)
        first = indexer.ensure_indexed()
        second = indexer.ensure_indexed()
        index.add_documents.assert_called_once_with([changed])
        self.assertEqual(first.chunk_count, 1)
        self.assertTrue(first.indexed)
        self.assertFalse(second.indexed)
        self.assertEqual(collection.count_documents.call_args.args[0], {"source": "data/b.md", "text": "changed"})

    def test_stale_semantic_versions_are_excluded_for_local_sources(self):
        current = Document(page_content="Python current", metadata={"source": "data/a.md"})
        stale = Document(page_content="Python stale", metadata={"source": "data/a.md"})
        external = Document(page_content="Other", metadata={"source": "external"})
        index = Mock()
        index.similarity_search.return_value = [stale, external]
        self.assertEqual(DocumentationRetriever(index, [current]).search("Python"), [current, external])


if __name__ == "__main__":
    unittest.main()
