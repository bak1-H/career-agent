import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from career_agent.adapters import mongo_atlas


def build_index(existing_index_names):
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
        collection.list_search_indexes.return_value = [{"name": name} for name in existing_index_names]
        index = mongo_atlas.MongoAtlasIndex(settings, embeddings)
    return index, store.return_value, collection


class MongoAtlasIndexTests(unittest.TestCase):
    def test_missing_search_index_is_created_with_embedding_dimensions(self):
        index, store, _ = build_index([])
        index.ensure_ready()
        store.create_vector_search_index.assert_called_once_with(
            dimensions=768,
            wait_until_complete=mongo_atlas.SEARCH_INDEX_TIMEOUT_SECONDS,
        )

    def test_existing_search_index_is_reused(self):
        index, store, _ = build_index(["vector_index"])
        index.ensure_ready()
        store.create_vector_search_index.assert_not_called()

    def test_contains_queries_by_source_and_text(self):
        index, _, collection = build_index([])
        collection.count_documents.return_value = 1
        self.assertTrue(index.contains("data/a.md", "text"))
        collection.count_documents.assert_called_once_with({"source": "data/a.md", "text": "text"}, limit=1)


if __name__ == "__main__":
    unittest.main()
