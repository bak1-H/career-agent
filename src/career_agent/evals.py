from __future__ import annotations

import json
import sys
from collections.abc import Sequence
from pathlib import Path

from career_agent.config import load_settings
from career_agent.graph import EVIDENCE_LIMIT
from career_agent.runtime import create_retrieval_runtime


QUESTIONS_PATH = Path(__file__).resolve().parents[2] / "evals" / "retrieval_questions.json"
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


def main() -> None:
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


if __name__ == "__main__":
    configure_output = getattr(sys.stdout, "reconfigure", None)
    if callable(configure_output):
        configure_output(encoding="utf-8")
    main()
