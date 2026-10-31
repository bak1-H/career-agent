from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from pymongo import MongoClient

from career_agent.config import Settings


SEARCH_INDEX_TIMEOUT_SECONDS = 300


class MongoAtlasIndex:
    def __init__(self, settings: Settings, embeddings: Embeddings):
        self._client = MongoClient(settings.mongodb_uri)
        self._collection = self._client[settings.mongodb_database][settings.mongodb_collection]
        self._embeddings = embeddings
        self._index_name = settings.atlas_vector_search_index_name
        self._store = MongoDBAtlasVectorSearch(
            embedding=embeddings,
            collection=self._collection,
            index_name=self._index_name,
            relevance_score_fn="cosine",
        )

    def add_documents(self, documents: list[Document]) -> object:
        return self._store.add_documents(documents)

    def similarity_search(self, query: str, k: int) -> list[Document]:
        return self._store.similarity_search(query, k=k)

    def contains(self, source: str, text: str) -> bool:
        return self._collection.count_documents({"source": source, "text": text}, limit=1) > 0

    def ensure_ready(self) -> None:
        existing_names = {index["name"] for index in self._collection.list_search_indexes()}
        if self._index_name in existing_names:
            return
        dimensions = len(self._embeddings.embed_query("dimension probe"))
        self._store.create_vector_search_index(
            dimensions=dimensions,
            wait_until_complete=SEARCH_INDEX_TIMEOUT_SECONDS,
        )

    def close(self) -> None:
        self._client.close()
