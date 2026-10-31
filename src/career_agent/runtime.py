from __future__ import annotations

from pathlib import Path

from langchain_ollama import OllamaEmbeddings

from career_agent.adapters.mongo_atlas import MongoAtlasIndex
from career_agent.config import Settings
from career_agent.graph import create_agent
from career_agent.retrieval import (
    DocumentationIndexer,
    DocumentationRetriever,
    IndexingReport,
    LangChainDocumentSplitter,
    LocalMarkdownSource,
)


LOCAL_PROFILE_DOCUMENTS = (
    "profile.md",
    "experience.md",
    "projects.md",
    "education.md",
    "skills.md",
)


def create_agent_runtime(settings: Settings, *, index_documents: bool = False) -> tuple[MongoAtlasIndex, object, IndexingReport]:
    index, indexer, retriever = create_retrieval_runtime(settings)

    try:
        indexing_report = indexer.ensure_indexed() if index_documents else IndexingReport(False, 0, 0)
        agent = None if index_documents else create_agent(settings, retriever)
    except Exception:
        index.close()
        raise

    return index, agent, indexing_report


def create_retrieval_runtime(settings: Settings) -> tuple[MongoAtlasIndex, DocumentationIndexer, DocumentationRetriever]:
    embeddings = OllamaEmbeddings(
        model=settings.ollama_embedding_model,
        base_url=settings.ollama_base_url,
    )
    index = MongoAtlasIndex(settings, embeddings)

    try:
        data_directory = Path(__file__).resolve().parents[2] / "data"
        document_paths = LOCAL_PROFILE_DOCUMENTS + tuple(
            path.name
            for path in sorted(data_directory.glob("project-*.md"))
            if path.is_file()
        )
        source = LocalMarkdownSource(data_directory)
        splitter = LangChainDocumentSplitter()
        fallback_documents = splitter.split(source.load(document_paths))
        indexer = DocumentationIndexer(source, splitter, index, paths=document_paths)
        retriever = DocumentationRetriever(index, fallback_documents)
    except Exception:
        index.close()
        raise

    return index, indexer, retriever
