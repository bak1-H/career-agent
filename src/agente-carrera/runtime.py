from __future__ import annotations

from pathlib import Path

from pymongo import MongoClient

from config import Settings
from graph import create_agent
from retrevial import (
    DocumentationIndexer,
    DocumentationRetriever,
    IndexingReport,
    LangChainDocumentSplitter,
    LocalMarkdownSource,
    create_vector_store,
)


LOCAL_PROFILE_DOCUMENTS = (
    "profile.md",
    "experience.md",
    "projects.md",
    "education.md",
    "skills.md",
)


def create_agent_runtime(settings: Settings, *, index_documents: bool = False) -> tuple[MongoClient, object, IndexingReport]:
    mongo_client = MongoClient(settings.mongodb_uri)

    try:
        collection = mongo_client[settings.mongodb_database][settings.mongodb_collection]
        vector_store = create_vector_store(settings, collection)
        data_directory = Path(__file__).resolve().parents[2] / "data"
        document_paths = LOCAL_PROFILE_DOCUMENTS + tuple(
            path.name
            for path in sorted(data_directory.glob("project-*.md"))
            if path.is_file()
        )
        source = LocalMarkdownSource(data_directory)
        splitter = LangChainDocumentSplitter()
        profile_documents = source.load(document_paths)
        fallback_documents = splitter.split(profile_documents)
        indexer = DocumentationIndexer(
            source,
            splitter,
            vector_store,
            collection,
            paths=document_paths,
        )
        indexing_report = indexer.ensure_indexed() if index_documents else IndexingReport(False, 0, 0)
        retriever = DocumentationRetriever(vector_store, fallback_documents)
        agent = None if index_documents else create_agent(settings, retriever)
    except Exception:
        mongo_client.close()
        raise

    return mongo_client, agent, indexing_report
