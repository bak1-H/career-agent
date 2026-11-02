from __future__ import annotations

import argparse
import re
import time
import json
import sys
import unicodedata
from collections.abc import Sequence
from pathlib import Path
from time import perf_counter

from langchain_core.messages import AIMessage, HumanMessage

from career_agent.config import load_settings
from career_agent.graph import EVIDENCE_LIMIT
from career_agent.runtime import create_agent_runtime, create_full_context_agent_runtime, create_retrieval_runtime


QUESTIONS_PATH = Path(__file__).resolve().parents[2] / "evals" / "retrieval_questions.json"
ANSWER_QUESTIONS_PATH = QUESTIONS_PATH.with_name("answer_questions.json")
FOLLOWUP_QUESTIONS_PATH = QUESTIONS_PATH.with_name("followup_questions.json")
CONVERSATION_QUESTIONS_PATH = QUESTIONS_PATH.with_name("conversation_questions.json")
TOPIC_SWITCH_QUESTIONS_PATH = QUESTIONS_PATH.with_name("topic_switch_questions.json")
CONVERSATION_TURN_PAUSE_SECONDS = 6
MIN_NEW_FOLLOWUP_FACTS = 2
RANKING_DEPTH = 10


def first_relevant_rank(ranked_sources: Sequence[str], accepted_sources: set[str]) -> int | None:
    for rank, source in enumerate(ranked_sources, start=1):
        if source in accepted_sources:
            return rank
    return None


def summarize(ranks: Sequence[int | None], evidence_limit: int) -> tuple[float, float, float]:
    hit_at_1 = sum(rank == 1 for rank in ranks) / len(ranks)
    hit_at_evidence_limit = sum(rank is not None and rank <= evidence_limit for rank in ranks) / len(ranks)
    mean_reciprocal_rank = sum(1 / rank for rank in ranks if rank) / len(ranks)
    return hit_at_1, hit_at_evidence_limit, mean_reciprocal_rank


def normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(character for character in decomposed if not unicodedata.combining(character))


def contains_expected(answer: str, expected: str) -> bool:
    return normalize(expected) in normalize(answer)


def open_agent(full_context: bool):
    settings = load_settings()
    if full_context:
        return None, create_full_context_agent_runtime(settings)
    index, agent, _ = create_agent_runtime(settings)
    return index, agent


def evaluate_answers(full_context: bool) -> None:
    cases = json.loads(ANSWER_QUESTIONS_PATH.read_text(encoding="utf-8"))
    index, agent = open_agent(full_context)
    passed = 0
    started_at = perf_counter()
    try:
        for case in cases:
            answer = agent.invoke({"messages": [HumanMessage(content=case["question"])]})["messages"][-1].text
            ok = contains_expected(answer, case["expected"])
            passed += ok
            print(f"{'OK ' if ok else 'BAD'}  {case['expected']:<12} {case['question']}")
    finally:
        if index:
            index.close()

    average_seconds = (perf_counter() - started_at) / len(cases)
    print(f"\nRespuestas correctas: {passed}/{len(cases)} ({passed / len(cases):.0%})  promedio: {average_seconds:.1f} s")


def new_facts(first: str, second: str, facts: Sequence[str]) -> list[str]:
    return [fact for fact in facts if contains_expected(second, fact) and not contains_expected(first, fact)]


def evaluate_followups(full_context: bool) -> None:
    cases = json.loads(FOLLOWUP_QUESTIONS_PATH.read_text(encoding="utf-8"))
    index, agent = open_agent(full_context)
    passed = 0
    try:
        for case in cases:
            first_question = HumanMessage(content=case["question"])
            first_answer = agent.invoke({"messages": [first_question]})["messages"][-1]
            second_answer = agent.invoke({"messages": [first_question, AIMessage(content=first_answer.text), HumanMessage(content=case["followup"])]})["messages"][-1]
            added = new_facts(first_answer.text, second_answer.text, case["facts"])
            ok = len(added) >= MIN_NEW_FOLLOWUP_FACTS
            passed += ok
            print(f"{'OK ' if ok else 'BAD'}  datos nuevos: {', '.join(added) or '-'}  ({case['question']} → {case['followup']})")
    finally:
        if index:
            index.close()

    print(f"\nSeguimientos sin repetir: {passed}/{len(cases)}")


def unrequested_facts(answer: str, allowed: Sequence[str] | str, facts: Sequence[str]) -> list[str]:
    if allowed == "*":
        return []
    return [fact for fact in facts if contains_expected(answer, fact) and fact not in allowed]


def ends_with_technology_list(answer: str, technologies: Sequence[str]) -> bool:
    sentences = [sentence for sentence in re.split(r"(?<=[.!?])\s+", answer.strip()) if sentence]
    return bool(sentences) and sum(contains_expected(sentences[-1], technology) for technology in technologies) >= 2


def evaluate_conversation(full_context: bool) -> None:
    script = json.loads(CONVERSATION_QUESTIONS_PATH.read_text(encoding="utf-8"))
    index, agent = open_agent(full_context)
    messages: list = []
    unrequested_total = 0
    technology_tails = 0
    closing_questions = 0
    try:
        for turn in script["turns"]:
            messages.append(HumanMessage(content=turn["question"]))
            answer = agent.invoke({"messages": list(messages)})["messages"][-1].text
            extra = unrequested_facts(answer, turn["allowed"], script["facts"])
            tail = ends_with_technology_list(answer, script["technologies"])
            unrequested_total += len(extra)
            technology_tails += tail
            closing_questions += answer.rstrip().endswith("?")
            print(f"{len(extra)} no pedidos: {', '.join(extra) or '-'}  cierre con tecnologías: {'sí' if tail else 'no'}  ({turn['question']})")
            messages.append(AIMessage(content=answer))
            time.sleep(CONVERSATION_TURN_PAUSE_SECONDS)
    finally:
        if index:
            index.close()

    turns = len(script["turns"])
    print(f"\nDatos no pedidos: {unrequested_total}  cierres con lista de tecnologías: {technology_tails}/{turns}  cierres con pregunta: {closing_questions}/{turns}")


def first_retrieved_sources(agent, messages: list) -> list[str]:
    for update in agent.stream({"messages": messages}, stream_mode="updates"):
        if "retrieve" in update:
            return [str(document.metadata.get("source", "")) for document in update["retrieve"]["documents"]]
    return []


def evaluate_topic_switch() -> None:
    cases = json.loads(TOPIC_SWITCH_QUESTIONS_PATH.read_text(encoding="utf-8"))
    index, agent = open_agent(False)
    ranks = []
    try:
        for case in cases:
            messages = [HumanMessage(content=case["previous"]), AIMessage(content=case["previous_answer"]), HumanMessage(content=case["question"])]
            ranked_sources = first_retrieved_sources(agent, messages)
            rank = first_relevant_rank(ranked_sources, set(case["sources"]))
            ranks.append(rank)
            top_source = ranked_sources[0] if ranked_sources else "-"
            print(f"{rank or '-':>2}  {top_source:<35} {case['previous']} → {case['question']}")
    finally:
        index.close()

    hit_at_1, hit_at_evidence_limit, mean_reciprocal_rank = summarize(ranks, EVIDENCE_LIMIT)
    print(f"\nHit@1: {hit_at_1:.0%}  Hit@{EVIDENCE_LIMIT}: {hit_at_evidence_limit:.0%}  MRR: {mean_reciprocal_rank:.3f}  ({len(ranks)} cambios de turno)")


def evaluate_retrieval() -> None:
    cases = json.loads(QUESTIONS_PATH.read_text(encoding="utf-8"))
    index, _, retriever = create_retrieval_runtime(load_settings())
    try:
        ranks = []
        for case in cases:
            documents = retriever.search(case["question"], limit=RANKING_DEPTH)
            ranked_sources = [str(document.metadata.get("source", "")) for document in documents]
            rank = first_relevant_rank(ranked_sources, set(case["sources"]))
            ranks.append(rank)
            top_source = ranked_sources[0] if ranked_sources else "-"
            print(f"{rank or '-':>2}  {top_source:<35} {case['question']}")
    finally:
        index.close()

    hit_at_1, hit_at_evidence_limit, mean_reciprocal_rank = summarize(ranks, EVIDENCE_LIMIT)
    print(
        f"\nHit@1: {hit_at_1:.0%}  Hit@{EVIDENCE_LIMIT}: {hit_at_evidence_limit:.0%}  "
        f"MRR: {mean_reciprocal_rank:.3f}  ({len(ranks)} preguntas, rank por chunk)"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--answers", action="store_true", help="Evaluate final answers instead of retrieval ranking")
    parser.add_argument("--followups", action="store_true", help="Evaluate whether follow-up answers avoid repeating the previous answer")
    parser.add_argument("--conversation", action="store_true", help="Evaluate unrequested repetition across a multi-turn conversation")
    parser.add_argument("--topic-switch", action="store_true", help="Evaluate second-turn retrieval when the topic changes or depends on the previous turn")
    parser.add_argument("--full-context", action="store_true", help="Send every profile document to the model instead of retrieving")
    arguments = parser.parse_args()
    if arguments.topic_switch:
        evaluate_topic_switch()
    elif arguments.conversation:
        evaluate_conversation(arguments.full_context)
    elif arguments.followups:
        evaluate_followups(arguments.full_context)
    elif arguments.answers:
        evaluate_answers(arguments.full_context)
    else:
        evaluate_retrieval()


if __name__ == "__main__":
    configure_output = getattr(sys.stdout, "reconfigure", None)
    if callable(configure_output):
        configure_output(encoding="utf-8")
    main()
