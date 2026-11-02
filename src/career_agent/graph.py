from __future__ import annotations

import re
import unicodedata
from typing import Literal

from langchain_core.documents import Document
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, HumanMessage, SystemMessage
from langchain_core.runnables import RunnableConfig
from langgraph.graph import END, START, MessagesState, StateGraph
from pydantic import BaseModel, Field

from career_agent.prompt import EVIDENCE_GRADER_PROMPT, QUERY_REWRITER_PROMPT, RAG_SYSTEM_PROMPT, SUGGESTIONS_PROMPT
from career_agent.retrieval import DocumentationRetriever, _search_terms


EVIDENCE_LIMIT = 5
PROMPT_CHAR_BUDGET = 12_000
GRADING_EXCERPT_LIMIT = 1_200
MAX_QUERY_REWRITES = 1
PREVIOUS_ANSWER_LIMIT = 400
PREVIOUS_ANSWERS_KEPT = 3
FOLLOW_UP_WORDS = frozenset({"si", "dale", "ok", "okay", "vale", "claro", "bueno", "porfa", "mas", "y", "eso", "que", "cuentame", "dime", "sigue", "continua"})
FOLLOW_UP_PREFIXES = ("cuentame mas", "dime mas", "y eso", "sigue")
PREVIOUS_ANSWER_TAIL_LIMIT = 300
MAX_SUGGESTIONS = 2
MAX_SUGGESTION_LENGTH = 60
SMALL_TALK_ANCHORS = frozenset({"hola", "holi", "hey", "buenas", "buenos", "saludos", "gracias", "chao", "chau", "adios", "hasta"})
SMALL_TALK_WORDS = SMALL_TALK_ANCHORS | frozenset({"buen", "dia", "dias", "tardes", "noches", "como", "estas", "esta", "que", "tal", "muchas", "mil", "luego", "pronto", "nos", "vemos"})
FAREWELL_WORDS = frozenset({"chao", "chau", "adios", "hasta"})
SMALL_TALK_REPLIES = {
    "greeting": "¡Hola! 👋 Soy el asistente de Maximiliano. Puedes preguntarme por sus proyectos, su experiencia o sus habilidades.",
    "thanks": "¡Con gusto! 😊 Si quieres saber algo más sobre Maximiliano, aquí estoy.",
    "farewell": "¡Gracias por pasar! 👋 Si necesitas contactarlo, usa el formulario del portafolio.",
}
DEFAULT_SUGGESTIONS = ["¿En qué proyectos ha trabajado?", "¿Cuál es su formación académica?"]


class AssistantReply(BaseModel):
    answer: str = Field(description="Respuesta para el visitante, en texto plano")
    suggestions: list[str] = Field(default_factory=list, description="Entre 0 y 2 preguntas breves que el visitante podría hacer a continuación")


class EvidenceGrade(BaseModel):
    sufficient: bool = Field(description="True only if some fragment contains the requested fact")


class SearchQuery(BaseModel):
    query: str = Field(description="Search query to retrieve the fact from the resume documents")


class AgentState(MessagesState, total=False):
    retrieval_query: str
    documents: list[Document]
    evidence_sufficient: bool
    query_rewrites: int
    suggestions: list[str]


def _normalize(text: str) -> str:
    stripped = "".join(char for char in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(char))
    return " ".join(re.sub(r"[¿?¡!.,;:]", " ", stripped).split())


def is_follow_up(question: str) -> bool:
    normalized = _normalize(question)
    return set(normalized.split()) <= FOLLOW_UP_WORDS or normalized.startswith(FOLLOW_UP_PREFIXES)


def small_talk_kind(question: str) -> str | None:
    words = set(_normalize(question).split())
    if not words or not words <= SMALL_TALK_WORDS or not words & SMALL_TALK_ANCHORS:
        return None
    if "gracias" in words:
        return "thanks"
    return "farewell" if words & FAREWELL_WORDS else "greeting"


def _last_question(state: AgentState) -> str:
    return next((message.text for message in reversed(state["messages"]) if isinstance(message, HumanMessage)), "")


def _previous_answer_tail(state: AgentState) -> str:
    messages = state["messages"]
    last_question = max((position for position, message in enumerate(messages) if isinstance(message, HumanMessage)), default=0)
    answers = [message.text for message in messages[:last_question] if isinstance(message, AIMessage)]
    return answers[-1][-PREVIOUS_ANSWER_TAIL_LIMIT:].strip() if answers else ""


def _reference(state: AgentState, question: str, previous_question: str) -> str:
    tail = _previous_answer_tail(state) if is_follow_up(question) else ""
    return f"{previous_question}\n{tail}".strip() if tail else previous_question


def _clean_suggestions(suggestions: list[str]) -> list[str]:
    cleaned = [suggestion.strip() for suggestion in suggestions if isinstance(suggestion, str)]
    return [suggestion for suggestion in cleaned if 0 < len(suggestion) <= MAX_SUGGESTION_LENGTH][:MAX_SUGGESTIONS]


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


def _previous_answers(state: AgentState) -> list[str]:
    messages = state["messages"]
    last_question = max((position for position, message in enumerate(messages) if isinstance(message, HumanMessage)), default=0)
    answers = [message.text[:PREVIOUS_ANSWER_LIMIT] for message in messages[:last_question] if isinstance(message, AIMessage)]
    return answers[-PREVIOUS_ANSWERS_KEPT:]


def _history(state: AgentState, previous_question: str) -> str:
    history = (
        "Pregunta anterior (solo contexto de referencia, nunca evidencia; "
        "la pregunta actual tiene prioridad):\n" + previous_question + "\n\n"
        if previous_question else ""
    )
    previous_answers = _previous_answers(state)
    if previous_answers:
        history += (
            "Tus respuestas anteriores en esta conversación (no son evidencia; no repitas sus datos "
            "salvo que la pregunta actual los pida):\n" + "\n".join(f"- {answer}" for answer in previous_answers) + "\n\n"
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
    replier = model.with_structured_output(AssistantReply, include_raw=True)
    generation_prompt = f"{RAG_SYSTEM_PROMPT}\n{SUGGESTIONS_PROMPT}"

    def route_entry(state: AgentState) -> Literal["small_talk", "retrieve"]:
        return "small_talk" if small_talk_kind(_last_question(state)) else "retrieve"

    def small_talk(state: AgentState):
        reply = SMALL_TALK_REPLIES[small_talk_kind(_last_question(state))]
        return {"messages": [AIMessage(content=reply)], "suggestions": list(DEFAULT_SUGGESTIONS)}

    def retrieve(state: AgentState):
        question, previous_question, _ = _conversation(state)
        reference = _reference(state, question, previous_question)
        query = state.get("retrieval_query") or (f"{question}\n{reference}" if reference else question)
        return {"retrieval_query": query, "documents": retriever.search(query, limit=EVIDENCE_LIMIT)}

    def grade_evidence(state: AgentState, config: RunnableConfig):
        documents = state.get("documents", [])
        if not documents:
            return {"evidence_sufficient": False}
        question, previous_question, _ = _conversation(state)
        reference = _reference(state, question, previous_question)
        context = f"Pregunta anterior:\n{reference}\n\n" if reference else ""
        request = [
            SystemMessage(content=EVIDENCE_GRADER_PROMPT),
            HumanMessage(content=f"Fragmentos:\n{_fragments(documents, f'{reference}\n{question}', GRADING_EXCERPT_LIMIT)}\n\n{context}Pregunta actual:\n{question}"),
        ]
        return {"evidence_sufficient": evidence_grader.invoke(request, config=config).sufficient}

    def route_after_grading(state: AgentState) -> Literal["generate", "rewrite_query"]:
        if state.get("evidence_sufficient") or state.get("query_rewrites", 0) >= MAX_QUERY_REWRITES:
            return "generate"
        return "rewrite_query"

    def rewrite_query(state: AgentState, config: RunnableConfig):
        question, previous_question, _ = _conversation(state)
        reference = _reference(state, question, previous_question)
        context = f"Pregunta anterior:\n{reference}\n\n" if reference else ""
        request = [SystemMessage(content=QUERY_REWRITER_PROMPT), HumanMessage(content=f"{context}Pregunta:\n{question}")]
        rewritten = query_rewriter.invoke(request, config=config).query.strip()
        return {"retrieval_query": rewritten or question, "query_rewrites": state.get("query_rewrites", 0) + 1}

    def generate(state: AgentState, config: RunnableConfig):
        question, previous_question, remaining = _conversation(state)
        history = _history(state, previous_question)
        remaining -= len(history) + len(SUGGESTIONS_PROMPT) + 1
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
        request = [SystemMessage(content=generation_prompt), HumanMessage(content=f"{history}Evidencia:\n{context}\n\nPregunta:\n{question}")]
        reply = replier.invoke(request, config=config)
        raw, parsed = reply["raw"], reply.get("parsed")
        if isinstance(parsed, AssistantReply) and parsed.answer.strip():
            message = AIMessage(
                content=parsed.answer.strip(),
                id=raw.id,
                usage_metadata=raw.usage_metadata,
                response_metadata=raw.response_metadata,
            )
            suggestions = _clean_suggestions(parsed.suggestions) if documents else []
        else:
            message, suggestions = raw, []
        return {
            "messages": [message],
            "suggestions": suggestions,
            "retrieval_query": "",
            "documents": [],
            "evidence_sufficient": False,
            "query_rewrites": 0,
        }

    graph = StateGraph(AgentState)
    graph.add_node("small_talk", small_talk)
    graph.add_node("retrieve", retrieve)
    graph.add_node("grade_evidence", grade_evidence)
    graph.add_node("rewrite_query", rewrite_query)
    graph.add_node("generate", generate)
    graph.add_conditional_edges(START, route_entry)
    graph.add_edge("small_talk", END)
    graph.add_edge("retrieve", "grade_evidence")
    graph.add_conditional_edges("grade_evidence", route_after_grading)
    graph.add_edge("rewrite_query", "retrieve")
    graph.add_edge("generate", END)
    return graph.compile()
