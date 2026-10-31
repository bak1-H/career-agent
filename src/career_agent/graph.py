from __future__ import annotations

from typing import Literal

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel, Field

from career_agent.prompt import EVIDENCE_GRADER_PROMPT, QUERY_REWRITER_PROMPT, RAG_SYSTEM_PROMPT
from career_agent.retrieval import DocumentationRetriever, _search_terms


EVIDENCE_LIMIT = 5
PROMPT_CHAR_BUDGET = 12_000
GRADING_EXCERPT_LIMIT = 1_200
MAX_QUERY_REWRITES = 1
PREVIOUS_ANSWER_LIMIT = 600


class EvidenceGrade(BaseModel):
    sufficient: bool = Field(description="True only if some fragment contains the requested fact")


class SearchQuery(BaseModel):
    query: str = Field(description="Search query to retrieve the fact from the resume documents")


class AgentState(MessagesState, total=False):
    retrieval_query: str
    documents: list[Document]
    evidence_sufficient: bool
    query_rewrites: int


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


def _conversation(state: AgentState) -> tuple[str, str, int]:
    user_questions = [message.text for message in state["messages"] if isinstance(message, HumanMessage)]
    question = user_questions[-1] if user_questions else ""
    if not question.strip():
        raise ValueError("A non-empty user question is required")
    remaining = PROMPT_CHAR_BUDGET - len(RAG_SYSTEM_PROMPT) - len(question)
    if remaining < 256:
        raise ValueError("Question exceeds the configured context budget")
    previous_question = user_questions[-2][:min(512, max(0, remaining - 768))] if len(user_questions) > 1 else ""
    return question, previous_question, remaining


def _previous_answer(state: AgentState) -> str:
    messages = state["messages"]
    if len(messages) < 2 or not isinstance(messages[-1], HumanMessage) or not isinstance(messages[-2], AIMessage):
        return ""
    return messages[-2].text[:PREVIOUS_ANSWER_LIMIT]


def _history(state: AgentState, previous_question: str) -> str:
    history = (
        "Pregunta anterior (solo contexto de referencia, nunca evidencia; "
        "la pregunta actual tiene prioridad):\n" + previous_question + "\n\n"
        if previous_question else ""
    )
    previous_answer = _previous_answer(state)
    if previous_answer:
        history += (
            "Tu respuesta anterior (no es evidencia; no repitas sus datos, "
            "agrega otros que estén en la evidencia):\n" + previous_answer + "\n\n"
        )
    return history


def create_full_context_agent(documents: list[Document], model: BaseChatModel):
    context = "\n\n".join(f"Fuente: {document.metadata.get('source', 'sin fuente identificada')}\n{document.page_content}" for document in documents)

    def answer(state: AgentState, config: RunnableConfig):
        question, previous_question, _ = _conversation(state)
        request = [
            SystemMessage(content=RAG_SYSTEM_PROMPT),
            HumanMessage(content=f"{_history(state, previous_question)}Evidencia:\n{context}\n\nPregunta:\n{question}"),
        ]
        return {"messages": [model.invoke(request, config=config)]}

    graph = StateGraph(AgentState)
    graph.add_node("answer", answer)
    graph.add_edge(START, "answer")
    graph.add_edge("answer", END)
    return graph.compile()


def _fragments(documents: list[Document], query: str, limit_per_fragment: int) -> str:
    return "\n\n".join(
        f"Fuente: {document.metadata.get('source', 'sin fuente identificada')}\n"
        + select_excerpt(document.page_content, query, limit_per_fragment)
        for document in documents
    )


def create_agent(retriever: DocumentationRetriever, model: BaseChatModel):
    evidence_grader = model.with_structured_output(EvidenceGrade)
    query_rewriter = model.with_structured_output(SearchQuery)

    def retrieve(state: AgentState):
        question, previous_question, _ = _conversation(state)
        query = state.get("retrieval_query") or (f"{question}\n{previous_question}" if previous_question else question)
        return {"retrieval_query": query, "documents": retriever.search(query, limit=EVIDENCE_LIMIT)}

    def grade_evidence(state: AgentState, config: RunnableConfig):
        documents = state.get("documents", [])
        if not documents:
            return {"evidence_sufficient": False}
        question, previous_question, _ = _conversation(state)
        context = f"Pregunta anterior:\n{previous_question}\n\n" if previous_question else ""
        request = [
            SystemMessage(content=EVIDENCE_GRADER_PROMPT),
            HumanMessage(content=f"Fragmentos:\n{_fragments(documents, f'{previous_question}\n{question}', GRADING_EXCERPT_LIMIT)}\n\n{context}Pregunta actual:\n{question}"),
        ]
        return {"evidence_sufficient": evidence_grader.invoke(request, config=config).sufficient}

    def route_after_grading(state: AgentState) -> Literal["generate", "rewrite_query"]:
        if state.get("evidence_sufficient") or state.get("query_rewrites", 0) >= MAX_QUERY_REWRITES:
            return "generate"
        return "rewrite_query"

    def rewrite_query(state: AgentState, config: RunnableConfig):
        question, previous_question, _ = _conversation(state)
        context = f"Pregunta anterior:\n{previous_question}\n\n" if previous_question else ""
        request = [SystemMessage(content=QUERY_REWRITER_PROMPT), HumanMessage(content=f"{context}Pregunta:\n{question}")]
        rewritten = query_rewriter.invoke(request, config=config).query.strip()
        return {"retrieval_query": rewritten or question, "query_rewrites": state.get("query_rewrites", 0) + 1}

    def generate(state: AgentState, config: RunnableConfig):
        question, previous_question, remaining = _conversation(state)
        history = _history(state, previous_question)
        remaining -= len(history)
        documents = state.get("documents", [])
        query = state.get("retrieval_query") or question
        evidence = []
        for position, document in enumerate(documents):
            source = str(document.metadata.get("source", "sin fuente identificada"))[:160]
            header = f"Fuente: {source}\nFragmento (puede estar incompleto):\n"
            allowance = min(1800, remaining // (len(documents) - position))
            excerpt = select_excerpt(document.page_content, f"{question}\n{query}", max(0, allowance - len(header)))
            evidence.append(header + excerpt)
            remaining -= len(header) + len(excerpt) + 2
        context = "\n\n".join(evidence) or "No se recuperó evidencia relevante."
        request = [SystemMessage(content=RAG_SYSTEM_PROMPT), HumanMessage(content=f"{history}Evidencia:\n{context}\n\nPregunta:\n{question}")]
        return {
            "messages": [model.invoke(request, config=config)],
            "retrieval_query": "",
            "documents": [],
            "evidence_sufficient": False,
            "query_rewrites": 0,
        }

    graph = StateGraph(AgentState)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade_evidence", grade_evidence)
    graph.add_node("rewrite_query", rewrite_query)
    graph.add_node("generate", generate)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "grade_evidence")
    graph.add_conditional_edges("grade_evidence", route_after_grading)
    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("generate", END)
    return graph.compile()
