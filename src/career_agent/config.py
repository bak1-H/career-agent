from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


REQUIRED_ENVIRONMENT_VARIABLES = (
    "GOOGLE_API_KEY",
    "MONGODB_URI",
    "MONGODB_DATABASE",
    "MONGODB_COLLECTION",
    "ATLAS_VECTOR_SEARCH_INDEX_NAME",
)
DEFAULT_CHAT_MODEL = "gemini-3.5-flash-lite"
DEFAULT_EMBEDDING_MODEL = "gemini-embedding-2"
DEFAULT_EMBEDDING_DIMENSIONS = 768


@dataclass(frozen=True)
class Settings:
    google_api_key: str
    mongodb_uri: str
    mongodb_database: str
    mongodb_collection: str
    atlas_vector_search_index_name: str
    gemini_chat_model: str = DEFAULT_CHAT_MODEL
    gemini_embedding_model: str = DEFAULT_EMBEDDING_MODEL
    embedding_dimensions: int = DEFAULT_EMBEDDING_DIMENSIONS


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")
    missing_variables = [name for name in REQUIRED_ENVIRONMENT_VARIABLES if not os.environ.get(name)]
    if missing_variables:
        missing = ", ".join(missing_variables)
        raise RuntimeError(f"Missing required environment variables: {missing}")

    return Settings(
        google_api_key=os.environ["GOOGLE_API_KEY"],
        mongodb_uri=os.environ["MONGODB_URI"],
        mongodb_database=os.environ["MONGODB_DATABASE"],
        mongodb_collection=os.environ["MONGODB_COLLECTION"],
        atlas_vector_search_index_name=os.environ["ATLAS_VECTOR_SEARCH_INDEX_NAME"],
        gemini_chat_model=os.environ.get("GEMINI_CHAT_MODEL") or DEFAULT_CHAT_MODEL,
        gemini_embedding_model=os.environ.get("GEMINI_EMBEDDING_MODEL") or DEFAULT_EMBEDDING_MODEL,
        embedding_dimensions=int(os.environ.get("EMBEDDING_DIMENSIONS") or DEFAULT_EMBEDDING_DIMENSIONS),
    )
