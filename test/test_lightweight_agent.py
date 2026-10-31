import unittest
from unittest.mock import Mock


from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from career_agent.graph import EVIDENCE_LIMIT, PROMPT_CHAR_BUDGET, create_agent, select_excerpt
from career_agent.retrieval import DocumentationIndexer, DocumentationRetriever


class FakeChatModel:
    def __init__(self, generate, grades=(True,), rewrites=("consulta reescrita",)):
        self._generate = RunnableLambda(generate)
        self._grades = list(grades)
        self._rewrites = list(rewrites)
        self.grade_requests = []
        self.rewrite_requests = []

    def with_structured_output(self, schema):
        if schema.__name__ == "EvidenceGrade":
            return RunnableLambda(lambda messages: self._grade(schema, messages))
        return RunnableLambda(lambda messages: self._rewrite(schema, messages))

    def _grade(self, schema, messages):
        self.grade_requests.append(messages)
        return schema(sufficient=self._grades.pop(0))

    def _rewrite(self, schema, messages):
        self.rewrite_requests.append(messages)
        return schema(query=self._rewrites.pop(0))

    def invoke(self, messages, config=None):
        return self._generate.invoke(messages, config=config)


def answering(content="Respuesta final."):
    return FakeChatModel(lambda messages: AIMessage(content=content))


class LightweightAgentTests(unittest.TestCase):
    def test_one_generation_with_bounded_evidence_and_callbacks(self):
        calls = []
        def generate(messages, config):
            calls.append((messages, config))
            return AIMessage(content="Respuesta final.", response_metadata={"eval_count": 12})
        model = FakeChatModel(generate)
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
        result = create_agent(retriever, FakeChatModel(lambda messages: response)).invoke({"messages": [HumanMessage(content="Pregunta")]})
        self.assertEqual(result["messages"][-1], response)

    def test_insufficient_evidence_triggers_one_rewrite_and_new_search(self):
        retriever = Mock()
        retriever.search.side_effect = [
            [Document(page_content="Resumen sin el dato", metadata={"source": "data/profile.md"})],
            [Document(page_content="Ubicación: Santiago, Chile", metadata={"source": "data/profile.md"})],
        ]
        model = FakeChatModel(lambda messages: AIMessage(content="Vive en Santiago."), grades=(False, True), rewrites=("ubicación ciudad",))
        result = create_agent(retriever, model).invoke({"messages": [HumanMessage(content="¿Dónde vive?")]})
        self.assertEqual([call.args[0] for call in retriever.search.call_args_list], ["¿Dónde vive?", "ubicación ciudad"])
        self.assertEqual(len(model.rewrite_requests), 1)
        self.assertEqual(result["messages"][-1].content, "Vive en Santiago.")
        self.assertEqual((result["retrieval_query"], result["documents"], result["query_rewrites"]), ("", [], 0))

    def test_rewrites_stop_after_the_limit_and_still_answer(self):
        retriever = Mock()
        retriever.search.return_value = [Document(page_content="Sin relación", metadata={"source": "data/skills.md"})]
        model = FakeChatModel(lambda messages: AIMessage(content="No hay evidencia."), grades=(False, False), rewrites=("go golang",))
        result = create_agent(retriever, model).invoke({"messages": [HumanMessage(content="¿Sabe Go?")]})
        self.assertEqual(retriever.search.call_count, 2)
        self.assertEqual((len(model.grade_requests), len(model.rewrite_requests)), (2, 1))
        self.assertEqual(result["messages"][-1].content, "No hay evidencia.")

    def test_empty_retrieval_is_graded_without_calling_the_model(self):
        retriever = Mock()
        retriever.search.return_value = []
        model = FakeChatModel(lambda messages: AIMessage(content="Sin evidencia."), grades=(), rewrites=("otra consulta",))
        create_agent(retriever, model).invoke({"messages": [HumanMessage(content="Pregunta")]})
        self.assertEqual(model.grade_requests, [])
        self.assertEqual(len(model.rewrite_requests), 1)

    def test_relevant_late_paragraph_is_retained(self):
        text = "Unrelated " * 1000 + "\n\nPython evidence near the end."
        self.assertIn("Python evidence", select_excerpt(text, "Python", 100))

    def test_followup_shows_previous_answer_only_as_labeled_non_evidence(self):
        calls = []
        def generate(messages, config):
            calls.append(messages)
            return AIMessage(content="Grounded answer")
        retriever = Mock()
        retriever.search.return_value = [Document(page_content="Current source", metadata={"source": "data/project.md"})]
        agent = create_agent(retriever, FakeChatModel(generate))
        result = agent.invoke({"messages": [
            HumanMessage(content="Old unrelated topic"),
            AIMessage(content="Old answer"),
            HumanMessage(content="What does Control de Activos solve?" + " context" * 1000),
            AIMessage(content="Unverified assistant assertion" + " detail" * 1000),
            HumanMessage(content="And which technologies does it use?"),
        ]})
        self.assertEqual(len(calls), 1)
        query = retriever.search.call_args.args[0]
        self.assertTrue(query.startswith("And which technologies does it use?"))
        self.assertIn("Control de Activos", query)
        self.assertNotIn("Unverified assistant assertion", query)
        self.assertLess(len(query), 600)
        prompt = calls[0][1].content
        self.assertIn("Control de Activos", prompt)
        self.assertIn("la pregunta actual tiene prioridad", prompt)
        label = "Tu respuesta anterior (no es evidencia"
        self.assertIn(label, prompt)
        self.assertLess(prompt.index(label), prompt.index("Unverified assistant assertion"))
        self.assertLess(prompt.index("Unverified assistant assertion"), prompt.index("Evidencia:"))
        self.assertLess(prompt.count(" detail"), 100)
        self.assertNotIn("Old unrelated topic", prompt)
        self.assertNotIn("Old answer", prompt)
        self.assertEqual(result["messages"][-1].content, "Grounded answer")

    def test_oversized_question_is_rejected_without_retrieval_or_generation(self):
        retriever = Mock()
        model = Mock()
        model.with_structured_output.return_value = Mock()
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
