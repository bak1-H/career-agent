import unittest
from unittest.mock import Mock

from langchain_core.messages import AIMessage
from starlette.testclient import TestClient

from career_agent.api import MAX_QUESTION_LENGTH, RateLimiter, create_app


def build_client(agent, rate_limiter=None):
    index = Mock()
    client = TestClient(create_app(lambda: (index, agent, None), rate_limiter or RateLimiter(100, 1000)))
    return client, index


class AskEndpointTests(unittest.TestCase):
    def test_answer_comes_from_the_agent_with_previous_question_first(self):
        agent = Mock()
        agent.invoke.return_value = {"messages": [AIMessage(content="Respuesta")]}
        client, index = build_client(agent)
        with client:
            response = client.post("/ask", json={"question": "¿Y el backend?", "previous_question": "¿Qué es Control de Activos?"})
        self.assertEqual(response.json(), {"answer": "Respuesta"})
        messages = agent.invoke.call_args.args[0]["messages"]
        self.assertEqual([message.content for message in messages], ["¿Qué es Control de Activos?", "¿Y el backend?"])
        index.close.assert_called_once()

    def test_previous_answer_is_sent_between_the_questions(self):
        agent = Mock()
        agent.invoke.return_value = {"messages": [AIMessage(content="Más detalle")]}
        client, _ = build_client(agent)
        with client:
            response = client.post("/ask", json={"question": "si", "previous_question": "¿Cuál fue su último trabajo?", "previous_answer": "Falabella."})
        self.assertEqual(response.status_code, 200)
        messages = agent.invoke.call_args.args[0]["messages"]
        self.assertEqual([(type(message).__name__, message.content) for message in messages], [
            ("HumanMessage", "¿Cuál fue su último trabajo?"),
            ("AIMessage", "Falabella."),
            ("HumanMessage", "si"),
        ])

    def test_invalid_payloads_are_rejected_without_calling_the_agent(self):
        agent = Mock()
        client, _ = build_client(agent)
        with client:
            for payload in [{}, {"question": "  "}, {"question": 3}, {"question": "x" * (MAX_QUESTION_LENGTH + 1)}, ["question"]]:
                with self.subTest(payload=payload):
                    self.assertEqual(client.post("/ask", json=payload).status_code, 400)
            self.assertEqual(client.post("/ask", content=b"not json").status_code, 400)
        agent.invoke.assert_not_called()

    def test_agent_failures_do_not_leak_details(self):
        agent = Mock()
        agent.invoke.side_effect = RuntimeError("secret detail")
        client, _ = build_client(agent)
        with client:
            response = client.post("/ask", json={"question": "Hola"})
        self.assertEqual(response.status_code, 502)
        self.assertNotIn("secret", response.text)

    def test_model_quota_errors_return_503_quickly_identifiable(self):
        class QuotaExhausted(Exception):
            code = 429
        agent = Mock()
        agent.invoke.side_effect = RuntimeError("wrapped")
        agent.invoke.side_effect.__cause__ = QuotaExhausted("RESOURCE_EXHAUSTED")
        client, _ = build_client(agent)
        with client:
            response = client.post("/ask", json={"question": "Hola"})
        self.assertEqual(response.status_code, 503)
        self.assertNotIn("RESOURCE_EXHAUSTED", response.text)

    def test_rate_limited_clients_receive_429(self):
        agent = Mock()
        agent.invoke.return_value = {"messages": [AIMessage(content="Respuesta")]}
        client, _ = build_client(agent, RateLimiter(per_minute_per_client=1, per_day=100))
        with client:
            self.assertEqual(client.post("/ask", json={"question": "Uno"}).status_code, 200)
            self.assertEqual(client.post("/ask", json={"question": "Dos"}).status_code, 429)


class RateLimiterTests(unittest.TestCase):
    def test_limits_reset_after_their_windows(self):
        now = [0.0]
        limiter = RateLimiter(per_minute_per_client=2, per_day=3, clock=lambda: now[0])
        self.assertTrue(limiter.allow("a"))
        self.assertTrue(limiter.allow("a"))
        self.assertFalse(limiter.allow("a"))
        self.assertTrue(limiter.allow("b"))
        self.assertFalse(limiter.allow("c"))
        now[0] = 61
        self.assertFalse(limiter.allow("a"))
        now[0] = 86_401
        self.assertTrue(limiter.allow("a"))


if __name__ == "__main__":
    unittest.main()
