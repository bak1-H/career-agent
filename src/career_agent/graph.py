from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, MessagesState, StateGraph

from career_agent.prompt import RAG_SYSTEM_PROMPT
from career_agent.retrieval import DocumentationRetriever, _search_terms


EVIDENCE_LIMIT = 5
PROMPT_CHAR_BUDGET = 12_000

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


def create_agent(retriever: DocumentationRetriever, model: BaseChatModel):
    def answer(state: MessagesState, config: RunnableConfig):
        user_questions = [message.text for message in state["messages"] if isinstance(message, HumanMessage)]
        question = user_questions[-1] if user_questions else ""
        if not question.strip():
            raise ValueError("A non-empty user question is required")
        remaining = PROMPT_CHAR_BUDGET - len(RAG_SYSTEM_PROMPT) - len(question)
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
        documents = retriever.search(retrieval_query, limit=EVIDENCE_LIMIT)
        evidence = []
        for position, document in enumerate(documents):
            source = str(document.metadata.get("source", "sin fuente identificada"))[:160]
            header = f"Fuente: {source}\nFragmento (puede estar incompleto):\n"
            allowance = min(1800, remaining // (len(documents) - position))
            excerpt = select_excerpt(document.page_content, retrieval_query, max(0, allowance - len(header)))
            evidence.append(header + excerpt)
            remaining -= len(header) + len(excerpt) + 2
        context = "\n\n".join(evidence) or "No se recuperó evidencia relevante."
        request = [SystemMessage(content=RAG_SYSTEM_PROMPT), HumanMessage(content=f"{history}Evidencia:\n{context}\n\nPregunta:\n{question}")]
        return {"messages": [model.invoke(request, config=config)]}

    graph = StateGraph(MessagesState)
    graph.add_node("answer", answer)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    return graph.compile()
