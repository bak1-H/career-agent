import json
import unittest
from unittest.mock import Mock

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.runnables import RunnableLambda
from career_agent.graph import EVIDENCE_LIMIT, PROMPT_CHAR_BUDGET, DEFAULT_SUGGESTIONS, create_agent, is_follow_up, select_excerpt, small_talk_kind
from career_agent.retrieval import DocumentationIndexer, DocumentationRetriever


class FakeChatModel:
    def __init__(self, generate, grades=(True,), rewrites=("consulta reescrita",), condensed="pregunta condensada"):
        self._generate = RunnableLambda(generate)
        self._grades = list(grades)
        self._rewrites = list(rewrites)
        self._condensed = condensed
        self.grade_requests = []
        self.rewrite_requests = []
        self.condense_requests = []

    def with_structured_output(self, schema, include_raw=False):
        if schema.__name__ == "EvidenceGrade":
            return RunnableLambda(lambda messages: self._grade(schema, messages))
        if schema.__name__ == "StandaloneQuestion":
            return RunnableLambda(lambda messages: self._condense(schema, messages))
        if schema.__name__ == "AssistantReply":
            return RunnableLambda(lambda messages, config: self._reply(schema, messages, config))
        return RunnableLambda(lambda messages: self._rewrite(schema, messages))

    def _reply(self, schema, messages, config):
        raw = self._generate.invoke(messages, config=config)
        try:
            parsed = schema.model_validate_json(raw.content)
        except ValueError:
            parsed = None
        return {"raw": raw, "parsed": parsed, "parsing_error": None}

    def _grade(self, schema, messages):
        self.grade_requests.append(messages)
        return schema(sufficient=self._grades.pop(0))

    def _condense(self, schema, messages):
        self.condense_requests.append(messages)
        return schema(question=self._condensed)

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
        model = FakeChatModel(generate, condensed="Which technologies does Control de Activos use?")
        agent = create_agent(retriever, model)
        result = agent.invoke({"messages": [
            HumanMessage(content="Old unrelated topic"),
            AIMessage(content="Old answer"),
            HumanMessage(content="What does Control de Activos solve?" + " context" * 1000),
            AIMessage(content="Unverified assistant assertion" + " detail" * 1000),
            HumanMessage(content="And which technologies does it use?"),
        ]})
        self.assertEqual(len(calls), 1)
        retriever.search.assert_called_once_with("Which technologies does Control de Activos use?", limit=EVIDENCE_LIMIT)
        condense_request = model.condense_requests[0][1].content
        self.assertIn("Control de Activos", condense_request)
        self.assertTrue(condense_request.endswith("And which technologies does it use?"))
        self.assertNotIn("Unverified assistant assertion", condense_request)
        self.assertNotIn("Old unrelated topic", condense_request)
        self.assertLess(len(condense_request), 700)
        prompt = calls[0][1].content
        self.assertIn("Control de Activos", prompt)
        self.assertIn("la pregunta actual tiene prioridad", prompt)
        label = "Tus respuestas anteriores en esta conversación (no son evidencia"
        self.assertIn(label, prompt)
        self.assertLess(prompt.index(label), prompt.index("Unverified assistant assertion"))
        self.assertLess(prompt.index("Unverified assistant assertion"), prompt.index("Evidencia:"))
        self.assertLess(prompt.count(" detail"), 100)
        self.assertNotIn("Old unrelated topic", prompt)
        self.assertIn("Old answer", prompt)
        self.assertEqual(result["messages"][-1].content, "Grounded answer")

    def test_structured_reply_becomes_plain_answer_and_suggestions(self):
        payload = json.dumps({"answer": " Maxi usó Python. ", "suggestions": ["¿Dónde lo usó?", "", "x" * 61, "¿Qué más hizo?", "¿Tercera?"]})
        response = AIMessage(content=payload, usage_metadata={"input_tokens": 1, "output_tokens": 2, "total_tokens": 3})
        retriever = Mock()
        retriever.search.return_value = [Document(page_content="Python", metadata={"source": "data/skills.md"})]
        result = create_agent(retriever, FakeChatModel(lambda messages: response)).invoke({"messages": [HumanMessage(content="¿Sabe Python?")]})
        self.assertEqual(result["messages"][-1].text, "Maxi usó Python.")
        self.assertEqual(result["messages"][-1].usage_metadata["total_tokens"], 3)
        self.assertEqual(result["suggestions"], ["¿Dónde lo usó?", "¿Qué más hizo?"])

    def test_unparseable_reply_falls_back_to_raw_text_without_suggestions(self):
        retriever = Mock()
        retriever.search.return_value = [Document(page_content="Python", metadata={"source": "data/skills.md"})]
        result = create_agent(retriever, answering("Texto plano {no json")).invoke({"messages": [HumanMessage(content="¿Sabe Python?")]})
        self.assertEqual(result["messages"][-1].text, "Texto plano {no json")
        self.assertEqual(result["suggestions"], [])

    def test_no_suggestions_without_evidence(self):
        payload = json.dumps({"answer": "No tengo ese dato.", "suggestions": ["¿Qué más sabe?"]})
        retriever = Mock()
        retriever.search.return_value = []
        model = FakeChatModel(lambda messages: AIMessage(content=payload), grades=(), rewrites=("otra",))
        result = create_agent(retriever, model).invoke({"messages": [HumanMessage(content="¿Sabe Go?")]})
        self.assertEqual(result["suggestions"], [])

    def test_generation_prompt_asks_for_suggestions(self):
        calls = []
        def generate(messages, config):
            calls.append(messages)
            return AIMessage(content="Respuesta")
        retriever = Mock()
        retriever.search.return_value = []
        create_agent(retriever, FakeChatModel(generate, rewrites=("otra",), grades=())).invoke({"messages": [HumanMessage(content="¿Sabe Go?")]})
        self.assertIn("suggestions", calls[0][0].content)

    def test_small_talk_detection(self):
        cases = {"Hola": "greeting", "¡Buenas tardes!": "greeting", "hola, ¿cómo estás?": "greeting", "Muchas gracias": "thanks", "chao": "farewell", "hasta luego": "farewell"}
        for question, kind in cases.items():
            with self.subTest(question=question):
                self.assertEqual(small_talk_kind(question), kind)
        for question in ["sí", "ok", "¿Qué?", "hola, ¿en qué proyectos trabajó?", "gracias, ¿sabe Go?", ""]:
            with self.subTest(question=question):
                self.assertIsNone(small_talk_kind(question))

    def test_small_talk_skips_retrieval_and_the_model(self):
        retriever = Mock()
        model = Mock()
        model.with_structured_output.return_value = Mock()
        result = create_agent(retriever, model).invoke({"messages": [HumanMessage(content="¡Hola!")]})
        retriever.search.assert_not_called()
        model.with_structured_output.return_value.invoke.assert_not_called()
        self.assertTrue(result["messages"][-1].content)
        self.assertEqual(result["suggestions"], DEFAULT_SUGGESTIONS)

    def test_follow_up_detection(self):
        for question in ["sí", "Si", "¡Dale!", "cuéntame más", "Cuentame mas", "más", "ok", "y eso?", "cuéntame más sobre eso por favor"]:
            with self.subTest(question=question):
                self.assertTrue(is_follow_up(question))
        for question in ["¿Qué tecnologías usó en Control de Activos?", "Describe su experiencia en la empresa anterior", "¿Qué estudió?", "¿Dónde vive?", "¿Sabe Python?"]:
            with self.subTest(question=question):
                self.assertFalse(is_follow_up(question))

    def test_follow_up_condensation_uses_the_tail_of_the_previous_answer(self):
        retriever = Mock()
        retriever.search.return_value = [Document(page_content="Zenly", metadata={"source": "data/projects.md"})]
        offer = "Trabajó en varios proyectos." + " relleno" * 100 + " ¿Quieres que te cuente sobre Zenly?"
        model = FakeChatModel(lambda messages: AIMessage(content="Respuesta final."), condensed="¿Qué es Zenly?")
        create_agent(retriever, model).invoke({"messages": [
            HumanMessage(content="¿En qué proyectos trabajó?"),
            AIMessage(content=offer),
            HumanMessage(content="sí, cuéntame más"),
        ]})
        condense_request = model.condense_requests[0][1].content
        self.assertIn("Zenly", condense_request)
        self.assertNotIn("Trabajó en varios proyectos", condense_request)
        self.assertEqual(retriever.search.call_args.args[0], "¿Qué es Zenly?")

    def test_follow_up_grader_and_rewriter_receive_the_previous_answer_tail(self):
        retriever = Mock()
        retriever.search.return_value = [Document(page_content="Sin dato", metadata={"source": "data/projects.md"})]
        model = FakeChatModel(lambda messages: AIMessage(content="Listo"), grades=(False, True), rewrites=("zenly proyecto",))
        create_agent(retriever, model).invoke({"messages": [
            HumanMessage(content="¿En qué proyectos trabajó?"),
            AIMessage(content="¿Te cuento sobre Zenly?"),
            HumanMessage(content="sí"),
        ]})
        self.assertIn("Zenly", model.grade_requests[0][1].content)
        self.assertIn("Zenly", model.rewrite_requests[0][1].content)

    def test_standalone_question_condensation_ignores_the_previous_answer(self):
        retriever = Mock()
        retriever.search.return_value = []
        model = FakeChatModel(lambda messages: AIMessage(content="Listo"), grades=(), rewrites=("otra",), condensed="¿Cuál es su formación académica?")
        create_agent(retriever, model).invoke({"messages": [
            HumanMessage(content="¿En qué proyectos trabajó?"),
            AIMessage(content="¿Te cuento sobre Zenly?"),
            HumanMessage(content="¿Cuál es su formación académica?"),
        ]})
        self.assertNotIn("Zenly", model.condense_requests[0][1].content)
        self.assertEqual(retriever.search.call_args_list[0].args[0], "¿Cuál es su formación académica?")

    def test_first_question_is_not_condensed(self):
        retriever = Mock()
        retriever.search.return_value = []
        model = FakeChatModel(lambda messages: AIMessage(content="Listo"), grades=(), rewrites=("otra",))
        create_agent(retriever, model).invoke({"messages": [HumanMessage(content="¿Dónde estudió?")]})
        self.assertEqual(model.condense_requests, [])
        self.assertEqual(retriever.search.call_args_list[0].args[0], "¿Dónde estudió?")

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
