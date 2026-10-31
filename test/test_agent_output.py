import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import Mock, patch


from langchain.messages import AIMessage, HumanMessage, ToolMessage

from langchain_core.outputs import ChatGeneration, LLMResult

from career_agent.cli import TokenUsageCollector, run_agent


class AgentOutputTests(unittest.TestCase):
    def test_prints_only_final_response_and_invokes_once(self):
        question = "¿Qué resuelve Control de Activos?"
        final_answer = "Centraliza el control de los activos."
        agent = Mock()
        agent.invoke.return_value = {"messages": [
            HumanMessage(content=question),
            AIMessage(content="Buscando evidencia", tool_calls=[{
                "name": "search_documentation", "args": {"query": question}, "id": "search-1",
            }]),
            ToolMessage(content="Migraciones independientes y otros proyectos", tool_call_id="search-1"),
            AIMessage(content="Resumen intermedio"),
            AIMessage(content=final_answer),
        ]}
        output = io.StringIO()

        with redirect_stdout(output), patch("career_agent.cli.perf_counter", side_effect=[10.0, 12.345]):
            run_agent(agent, question)

        self.assertEqual(output.getvalue(), final_answer + "\nTiempo: 2.35 s\nTokens: no disponibles\n")
        agent.invoke.assert_called_once()
        self.assertEqual(agent.invoke.call_args.args[0]["messages"], [HumanMessage(content=question)])

    def test_accumulates_model_calls_without_counting_alternatives_or_llm_output(self):
        collector = TokenUsageCollector()
        for input_tokens, output_tokens in [(10, 3), (20, 5)]:
            message = AIMessage(content="answer", usage_metadata={
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": input_tokens + output_tokens,
            })
            collector.on_llm_end(LLMResult(
                generations=[[ChatGeneration(message=message), ChatGeneration(message=message)]],
                llm_output={"token_usage": {"total_tokens": 999}},
            ))
        self.assertEqual((collector.input_tokens, collector.output_tokens, collector.total_tokens), (30, 8, 38))
        self.assertEqual(collector.reported_calls, 2)
        self.assertFalse(collector.missing_usage)

    def test_prints_partial_token_usage_from_callback(self):
        agent = Mock()
        def invoke(payload, config):
            callback = config["callbacks"][0]
            for usage in [None, {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12}]:
                callback.on_llm_end(LLMResult(generations=[[
                    ChatGeneration(message=AIMessage(content="answer", usage_metadata=usage)),
                ]]))
            return {"messages": [AIMessage(content="Final answer")]}
        agent.invoke.side_effect = invoke
        output = io.StringIO()
        with redirect_stdout(output), patch("career_agent.cli.perf_counter", side_effect=[0.0, 1.0]):
            run_agent(agent, "question")
        self.assertEqual(output.getvalue(), "Final answer\nTiempo: 1.00 s\nTokens reportados (parcial): entrada=10, salida=2, total=12\n")

    def test_missing_or_unfinished_final_response_raises_without_printing(self):
        unfinished_messages = [
            [],
            [HumanMessage(content="question")],
            [AIMessage(content="older answer"), ToolMessage(content="evidence", tool_call_id="search-1")],
            [AIMessage(content="   ")],
            [AIMessage(content="Searching", tool_calls=[{
                "name": "search_documentation", "args": {}, "id": "search-1",
            }])],
            [AIMessage(content="Searching", invalid_tool_calls=[{
                "name": "search_documentation", "args": "{", "id": "search-1", "error": "invalid arguments",
            }])],
        ]
        for messages in unfinished_messages:
            with self.subTest(messages=messages):
                agent = Mock()
                agent.invoke.return_value = {"messages": messages}
                output = io.StringIO()
                with redirect_stdout(output), self.assertRaisesRegex(RuntimeError, "respuesta final"):
                    run_agent(agent, "question")
                self.assertEqual(output.getvalue(), "")


if __name__ == "__main__":
    unittest.main()
