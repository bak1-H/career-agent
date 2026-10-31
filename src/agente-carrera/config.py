from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


REQUIRED_ENVIRONMENT_VARIABLES = (
    "OLLAMA_BASE_URL",
    "OLLAMA_CHAT_MODEL",
    "OLLAMA_EMBEDDING_MODEL",
    "MONGODB_URI",
    "MONGODB_DATABASE",
    "MONGODB_COLLECTION",
    "ATLAS_VECTOR_SEARCH_INDEX_NAME",
)


@dataclass(frozen=True)
class Settings:
    ollama_base_url: str
    ollama_chat_model: str
    ollama_embedding_model: str
    mongodb_uri: str
    mongodb_database: str
    mongodb_collection: str
    atlas_vector_search_index_name: str
    ollama_num_ctx: int = 4096
    ollama_num_predict: int = 384
    ollama_keep_alive: str = "10m"

    def __post_init__(self):
        if self.ollama_num_ctx < 2048:
            raise ValueError("OLLAMA_NUM_CTX must be at least 2048")
        if not 1 <= self.ollama_num_predict <= self.ollama_num_ctx // 2:
            raise ValueError("OLLAMA_NUM_PREDICT must be positive and at most half OLLAMA_NUM_CTX")


def load_settings() -> Settings:
    project_root = Path(__file__).resolve().parents[2]
    load_dotenv(project_root / ".env")
    missing_variables = [
        name for name in REQUIRED_ENVIRONMENT_VARIABLES if not os.environ.get(name)
    ]
    if missing_variables:
        missing = ", ".join(missing_variables)
        raise RuntimeError(f"Missing required environment variables: {missing}")

    return Settings(
        ollama_base_url=os.environ["OLLAMA_BASE_URL"],        ollama_chat_model=os.environ["OLLAMA_CHAT_MODEL"],
        ollama_embedding_model=os.environ["OLLAMA_EMBEDDING_MODEL"],
        mongodb_uri=os.environ["MONGODB_URI"],
        mongodb_database=os.environ["MONGODB_DATABASE"],
        mongodb_collection=os.environ["MONGODB_COLLECTION"],
        atlas_vector_search_index_name=os.environ[
            "ATLAS_VECTOR_SEARCH_INDEX_NAME"
        ],
        ollama_num_ctx=int(os.environ.get("OLLAMA_NUM_CTX", "4096")),
        ollama_num_predict=int(os.environ.get("OLLAMA_NUM_PREDICT", "384")),
        ollama_keep_alive=os.environ.get("OLLAMA_KEEP_ALIVE", "10m"),
    )
