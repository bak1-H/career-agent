import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from langchain_core.documents import Document

from career_agent.adapters import mongo_atlas


EMBEDDING_ID = "embedding-test:768"
VECTOR_FIELD = {"type": "vector", "path": "embedding", "numDimensions": 768, "similarity": "cosine"}
FILTER_FIELD = {"type": "filter", "path": mongo_atlas.EMBEDDING_ID_FIELD}


def build_index(existing_indexes):
    settings = SimpleNamespace(
        mongodb_uri="mongodb://unused",
        mongodb_database="database",
        mongodb_collection="collection",
        atlas_vector_search_index_name="vector_index",
    )
    embeddings = MagicMock()
    embeddings.embed_query.return_value = [0.0] * 768
    with patch.object(mongo_atlas, "MongoClient") as client, patch.object(mongo_atlas, "MongoDBAtlasVectorSearch") as store:
        collection = client.return_value.__getitem__.return_value.__getitem__.return_value
        collection.list_search_indexes.return_value = existing_indexes
        index = mongo_atlas.MongoAtlasIndex(settings, embeddings, EMBEDDING_ID)
    return index, store.return_value, collection


def search_index(*fields):
    return {"name": "vector_index", "latestDefinition": {"fields": list(fields)}}


class MongoAtlasIndexTests(unittest.TestCase):
    def test_missing_search_index_is_created_with_dimensions_and_filter(self):
        index, store, _ = build_index([])
        index.ensure_ready()
        store.create_vector_search_index.assert_called_once_with(
            dimensions=768,
            filters=[mongo_atlas.EMBEDDING_ID_FIELD],
            update=False,
            wait_until_complete=mongo_atlas.SEARCH_INDEX_TIMEOUT_SECONDS,
        )

    def test_matching_search_index_is_reused(self):
        index, store, _ = build_index([search_index(VECTOR_FIELD, FILTER_FIELD)])
        index.ensure_ready()
        store.create_vector_search_index.assert_not_called()

    def test_search_index_with_other_dimensions_or_without_filter_is_updated(self):
        for fields in [(VECTOR_FIELD | {"numDimensions": 3072}, FILTER_FIELD), (VECTOR_FIELD,)]:
            with self.subTest(fields=fields):
                index, store, _ = build_index([search_index(*fields)])
                index.ensure_ready()
                self.assertTrue(store.create_vector_search_index.call_args.kwargs["update"])

    def test_documents_are_tagged_and_searched_by_embedding_model(self):
        index, store, _ = build_index([])
        index.add_documents([Document(page_content="text", metadata={"source": "data/a.md"})])
        stored = store.add_documents.call_args.args[0][0]
        self.assertEqual(stored.metadata, {"source": "data/a.md", mongo_atlas.EMBEDDING_ID_FIELD: EMBEDDING_ID})
        index.similarity_search("query", k=3)
        store.similarity_search.assert_called_once_with("query", k=3, pre_filter={mongo_atlas.EMBEDDING_ID_FIELD: {"$eq": EMBEDDING_ID}})

    def test_contains_requires_the_current_embedding_model(self):
        index, _, collection = build_index([])
        collection.count_documents.return_value = 1
        self.assertTrue(index.contains("data/a.md", "text"))
        collection.count_documents.assert_called_once_with(
            {"source": "data/a.md", "text": "text", mongo_atlas.EMBEDDING_ID_FIELD: EMBEDDING_ID}, limit=1,
        )

    def test_remove_stale_drops_old_texts_and_other_embedding_models(self):
        index, _, collection = build_index([])
        collection.delete_many.return_value.deleted_count = 4
        self.assertEqual(index.remove_stale("data/a.md", {"b", "a"}), 4)
        collection.delete_many.assert_called_once_with({
            "source": "data/a.md",
            "$or": [
                {"text": {"$nin": ["a", "b"]}},
                {mongo_atlas.EMBEDDING_ID_FIELD: {"$ne": EMBEDDING_ID}},
            ],
        })


if __name__ == "__main__":
    unittest.main()
