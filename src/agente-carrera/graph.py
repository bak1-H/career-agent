from __future__ import annotations

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_ollama import ChatOllama
from langgraph.graph import END, START, MessagesState, StateGraph

from config import Settings
from prompt import RAG_SYSTEM_PROMPT
from retrevial import DocumentationRetriever, _search_terms


def select_excerpt(text: str, query: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    terms = _search_terms(query)
    paragraphs = text.split("\n\n")
    ranked = sorted(enumerate(paragraphs), key=lambda item: (-len(terms.intersection(_search_terms(item[1]))), item[0]))
    selected = []
    remaining = limit
    for position, paragraph in ranked:
        if remaining <= 0:
            break
        excerpt = paragraph[:remaining]
        selected.append((position, excerpt))
        remaining -= len(excerpt) + 2
    return "\n\n".join(text for _, text in sorted(selected))


def create_agent(settings: Settings, retriever: DocumentationRetriever):
    model = ChatOllama(
        model=settings.ollama_chat_model,
        base_url=settings.ollama_base_url,
        num_ctx=settings.ollama_num_ctx,
        num_predict=settings.ollama_num_predict,
        keep_alive=settings.ollama_keep_alive,
        temperature=0,
        reasoning=False,
    )

    response_prefix = "<think>\n</think>\n\n" if settings.ollama_chat_model.split(":")[0].split("/")[-1] == "qwen3" else ""

    def answer(state: MessagesState, config: RunnableConfig):
        user_questions = [message.text for message in state["messages"] if isinstance(message, HumanMessage)]
        question = user_questions[-1] if user_questions else ""
        if not question.strip():
            raise ValueError("A non-empty user question is required")
        input_budget = settings.ollama_num_ctx - settings.ollama_num_predict - 256
        remaining = input_budget - len(RAG_SYSTEM_PROMPT) - len(question) - len(response_prefix)
        if remaining < 256:
            raise ValueError("Question exceeds the configured context budget")
        previous_question = user_questions[-2][:min(512, max(0, remaining - 768))] if len(user_questions) > 1 else ""
        history = (
            "Pregunta anterior (solo contexto de referencia, nunca evidencia; "
            "la pregunta actual tiene prioridad):\n" + previous_question + "\n\n"
            if previous_question else ""
        )
        remaining -= len(history)
        retrieval_query = f"{question}\n{previous_question}" if previous_question else question
        documents = retriever.search(retrieval_query, limit=3)
        evidence = []
        for position, document in enumerate(documents):
            source = str(document.metadata.get("source", "sin fuente identificada"))[:160]
            header = f"Fuente: {source}\nFragmento (puede estar incompleto):\n"
            allowance = min(1800, remaining // (len(documents) - position))
            excerpt = select_excerpt(document.page_content, retrieval_query, max(0, allowance - len(header)))
            evidence.append(header + excerpt)
            remaining -= len(header) + len(excerpt) + 2
        context = "\n\n".join(evidence) or "No se recuperó evidencia relevante."
        request = [SystemMessage(content=RAG_SYSTEM_PROMPT), HumanMessage(content=f"{history}Evidencia:\n{context}\n\nPregunta:\n{question}\n\n/no_think")]
        if response_prefix:
            request.append(AIMessage(content=response_prefix))
        response = model.invoke(request, config=config)
        if response_prefix and isinstance(response.content, str):
            if "<think>" in response.content and "</think>" not in response.content:
                raise RuntimeError("The model did not complete its final response")
            if "</think>" in response.content:
                final_content = response.content.rsplit("</think>", 1)[1].strip()
                if not final_content or "<think>" in final_content:
                    raise RuntimeError("The model did not return a final response")
                response = response.model_copy(update={"content": final_content})
        return {"messages": [response]}

    graph = StateGraph(MessagesState)
    graph.add_node("answer", answer)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    return graph.compile()
