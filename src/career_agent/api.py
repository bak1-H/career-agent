from __future__ import annotations

import logging
import os
from collections import defaultdict, deque
from collections.abc import Callable
from contextlib import asynccontextmanager
from threading import Lock
from time import monotonic

from langchain_core.messages import AIMessage, HumanMessage
from langchain_google_genai.chat_models import GoogleRateLimitError
from starlette.applications import Starlette
from starlette.concurrency import run_in_threadpool
from starlette.middleware import Middleware
from starlette.middleware.cors import CORSMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from career_agent.config import load_settings
from career_agent.runtime import create_agent_runtime


logging.basicConfig(level=logging.WARNING)
logging.getLogger("career_agent").setLevel(logging.INFO)
logger = logging.getLogger(__name__)

MAX_QUESTION_LENGTH = 500
MAX_PREVIOUS_ANSWER_LENGTH = 4_000
MAX_HISTORY_TURNS = 3
REQUESTS_PER_MINUTE_PER_CLIENT = 10
REQUESTS_PER_DAY = 300


class RateLimiter:
    def __init__(self, per_minute_per_client: int, per_day: int, clock: Callable[[], float] = monotonic):
        self._per_minute_per_client = per_minute_per_client
        self._per_day = per_day
        self._clock = clock
        self._client_requests: dict[str, deque[float]] = defaultdict(deque)
        self._all_requests: deque[float] = deque()
        self._lock = Lock()

    def allow(self, client: str) -> bool:
        now = self._clock()
        with self._lock:
            client_requests = self._client_requests[client]
            _drop_older_than(client_requests, now - 60)
            _drop_older_than(self._all_requests, now - 86_400)
            if len(client_requests) >= self._per_minute_per_client or len(self._all_requests) >= self._per_day:
                return False
            client_requests.append(now)
            self._all_requests.append(now)
            return True


def _drop_older_than(timestamps: deque[float], limit: float) -> None:
    while timestamps and timestamps[0] <= limit:
        timestamps.popleft()


def _client_address(request: Request) -> str:
    forwarded_for = request.headers.get("x-forwarded-for", "")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_quota_error(error: BaseException | None) -> bool:
    while error is not None:
        if isinstance(error, GoogleRateLimitError) or getattr(error, "code", None) == 429:
            return True
        error = error.__cause__
    return False


def _read_text(payload: object, field: str, required: bool, max_length: int = MAX_QUESTION_LENGTH) -> str:
    value = payload.get(field, "") if isinstance(payload, dict) else ""
    if not isinstance(value, str) or (required and not value.strip()):
        raise ValueError(f"'{field}' must be a non-empty string")
    if len(value) > max_length:
        raise ValueError(f"'{field}' must have at most {max_length} characters")
    return value.strip()


def _read_history(payload: object) -> list[dict[str, str]] | None:
    raw = payload.get("history") if isinstance(payload, dict) else None
    if raw is None:
        return None
    if not isinstance(raw, list):
        raise ValueError("'history' must be a list")
    turns = []
    for position, turn in enumerate(raw[-MAX_HISTORY_TURNS:]):
        if not isinstance(turn, dict):
            raise ValueError(f"'history[{position}]' must be an object")
        turns.append({
            "question": _read_text(turn, "question", required=True),
            "answer": _read_text(turn, "answer", required=False, max_length=MAX_PREVIOUS_ANSWER_LENGTH),
        })
    return turns


def _build_messages(payload: object, question: str) -> list:
    history = _read_history(payload)
    if history is None:
        previous_question = _read_text(payload, "previous_question", required=False)
        previous_answer = _read_text(payload, "previous_answer", required=False, max_length=MAX_PREVIOUS_ANSWER_LENGTH)
        history = [{"question": previous_question, "answer": previous_answer}] if previous_question or previous_answer else []
    messages = []
    for turn in history:
        if turn["question"]:
            messages.append(HumanMessage(content=turn["question"]))
        if turn["answer"]:
            messages.append(AIMessage(content=turn["answer"]))
    return [*messages, HumanMessage(content=question)]


def create_app(load_runtime: Callable[[], tuple] = lambda: create_agent_runtime(load_settings()), rate_limiter: RateLimiter | None = None) -> Starlette:
    limiter = rate_limiter or RateLimiter(REQUESTS_PER_MINUTE_PER_CLIENT, REQUESTS_PER_DAY)
    state: dict[str, object] = {}

    @asynccontextmanager
    async def lifespan(app: Starlette):
        index, agent, _ = load_runtime()
        state["agent"] = agent
        try:
            yield
        finally:
            index.close()

    async def ask(request: Request) -> JSONResponse:
        if not limiter.allow(_client_address(request)):
            return JSONResponse({"error": "Too many requests, please try again later."}, status_code=429)
        try:
            payload = await request.json()
        except ValueError:
            return JSONResponse({"error": "The body must be valid JSON."}, status_code=400)
        try:
            question = _read_text(payload, "question", required=True)
            messages = _build_messages(payload, question)
        except ValueError as error:
            return JSONResponse({"error": str(error)}, status_code=400)

        started = monotonic()
        try:
            result = await run_in_threadpool(state["agent"].invoke, {"messages": messages})
            logger.info("request elapsed_ms=%.0f", (monotonic() - started) * 1000)
        except Exception as error:
            logger.exception("Agent invocation failed")
            if _is_quota_error(error):
                return JSONResponse({"error": "The assistant reached its usage limit for now."}, status_code=503)
            return JSONResponse({"error": "The assistant could not answer right now."}, status_code=502)
        return JSONResponse({"answer": result["messages"][-1].text, "suggestions": list(result.get("suggestions") or [])})

    async def health(request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    allowed_origins = [origin.strip() for origin in os.environ.get("ALLOWED_ORIGINS", "").split(",") if origin.strip()]
    return Starlette(
        routes=[Route("/ask", ask, methods=["POST"]), Route("/health", health, methods=["GET"])],
        middleware=[Middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=["POST"], allow_headers=["Content-Type"])],
        lifespan=lifespan,
    )


app = create_app()
