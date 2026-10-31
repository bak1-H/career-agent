from __future__ import annotations

import sys
import argparse
from threading import Lock
from time import perf_counter

from langchain.messages import AIMessage, HumanMessage
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import ChatGeneration

from config import load_settings
from runtime import create_agent_runtime

EXAMPLE_QUERY = "¿para que utilizas MongoDB"
class TokenUsageCollector(BaseCallbackHandler):
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.total_tokens = 0
        self.reported_calls = 0
        self.missing_usage = False
        self._lock = Lock()

    def on_llm_end(self, response, **kwargs):
        with self._lock:
            for generations in response.generations:
                generation = generations[0] if generations else None
                message = generation.message if isinstance(generation, ChatGeneration) else None
                usage = message.usage_metadata if isinstance(message, AIMessage) else None
                if usage is None:
                    self.missing_usage = True
                    continue
                self.input_tokens += usage["input_tokens"]
                self.output_tokens += usage["output_tokens"]
                self.total_tokens += usage["total_tokens"]
                self.reported_calls += 1


def run_agent(agent, query: str) -> None:
    usage = TokenUsageCollector()
    started_at = perf_counter()
    result = agent.invoke(
        {"messages": [HumanMessage(content=query)]},
        config={"callbacks": [usage]},
    )
    elapsed_seconds = perf_counter() - started_at
    messages = result.get("messages", [])
    if not messages:
        raise RuntimeError("El agente no devolvió una respuesta final.")
    final_message = messages[-1]
    if (
        not isinstance(final_message, AIMessage)
        or final_message.tool_calls
        or final_message.invalid_tool_calls
        or not final_message.text.strip()
    ):
        raise RuntimeError("El agente no devolvió una respuesta final de texto válida.")
    print(final_message.text)
    print(f"Tiempo: {elapsed_seconds:.2f} s")
    if not usage.reported_calls:
        print("Tokens: no disponibles")
    else:
        coverage = " (parcial)" if usage.missing_usage else ""
        print(
            f"Tokens reportados{coverage}: entrada={usage.input_tokens}, "
            f"salida={usage.output_tokens}, total={usage.total_tokens}"
        )


def print_indexing_result(report) -> None:
    if report.indexed:
        print(f"Loaded {report.document_count} documentation pages.")
        print(f"Indexed {report.chunk_count} chunks.")
        return

    print("La Documentacion Indexeada esta Lista.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--index", action="store_true", help="Index local documents and exit")
    arguments = parser.parse_args()
    settings = load_settings()
    mongo_client, agent, report = create_agent_runtime(settings, index_documents=arguments.index)
    try:
        if arguments.index:
            print_indexing_result(report)
        else:
            run_agent(agent, EXAMPLE_QUERY)
    finally:
        mongo_client.close()


if __name__ == "__main__":
    configure_output = getattr(sys.stdout, "reconfigure", None)
    if callable(configure_output):
        configure_output(encoding="utf-8")
    main()
