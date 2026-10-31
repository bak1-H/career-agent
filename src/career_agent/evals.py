from __future__ import annotations

import argparse
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
    parser.add_argument("--full-context", action="store_true", help="Send every profile document to the model instead of retrieving")
    arguments = parser.parse_args()
    if arguments.followups:
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
