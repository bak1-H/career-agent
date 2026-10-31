from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_mongodb import MongoDBAtlasVectorSearch
from pymongo import MongoClient

from career_agent.config import Settings


SEARCH_INDEX_TIMEOUT_SECONDS = 300
EMBEDDING_ID_FIELD = "embedding_model"


class MongoAtlasIndex:
    def __init__(self, settings: Settings, embeddings: Embeddings, embedding_id: str):
        self._client = MongoClient(settings.mongodb_uri)
        self._collection = self._client[settings.mongodb_database][settings.mongodb_collection]
        self._embeddings = embeddings
        self._embedding_id = embedding_id
        self._index_name = settings.atlas_vector_search_index_name
        self._store = MongoDBAtlasVectorSearch(
            embedding=embeddings,
            collection=self._collection,
            index_name=self._index_name,
            relevance_score_fn="cosine",
        )

    def add_documents(self, documents: list[Document]) -> object:
        return self._store.add_documents([
            Document(page_content=document.page_content, metadata=document.metadata | {EMBEDDING_ID_FIELD: self._embedding_id})
            for document in documents
        ])

    def similarity_search(self, query: str, k: int) -> list[Document]:
        return self._store.similarity_search(query, k=k, pre_filter={EMBEDDING_ID_FIELD: {"$eq": self._embedding_id}})

    def contains(self, source: str, text: str) -> bool:
        query = {"source": source, "text": text, EMBEDDING_ID_FIELD: self._embedding_id}
        return self._collection.count_documents(query, limit=1) > 0

    def remove_stale(self, source: str, current_texts: set[str]) -> int:
        result = self._collection.delete_many({
            "source": source,
            "$or": [
                {"text": {"$nin": sorted(current_texts)}},
                {EMBEDDING_ID_FIELD: {"$ne": self._embedding_id}},
            ],
        })
        return result.deleted_count

    def ensure_ready(self) -> None:
        dimensions = len(self._embeddings.embed_query("dimension probe"))
        existing = next((index for index in self._collection.list_search_indexes() if index["name"] == self._index_name), None)
        if existing is not None and _matches_definition(existing.get("latestDefinition", {}), dimensions):
            return
        self._store.create_vector_search_index(
            dimensions=dimensions,
            filters=[EMBEDDING_ID_FIELD],
            update=existing is not None,
            wait_until_complete=SEARCH_INDEX_TIMEOUT_SECONDS,
        )

    def close(self) -> None:
        self._client.close()


def _matches_definition(definition: dict, dimensions: int) -> bool:
    fields = definition.get("fields", [])
    has_vector = any(field.get("type") == "vector" and field.get("numDimensions") == dimensions for field in fields)
    has_filter = any(field.get("type") == "filter" and field.get("path") == EMBEDDING_ID_FIELD for field in fields)
    return has_vector and has_filter
