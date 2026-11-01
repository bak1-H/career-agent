from __future__ import annotations

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from career_agent.adapters.mongo_atlas import MongoAtlasIndex
from career_agent.config import Settings
from career_agent.graph import create_agent, create_full_context_agent
from career_agent.retrieval import (
    DocumentationIndexer,
    DocumentationRetriever,
    IndexingReport,
    LocalMarkdownSource,
    MarkdownSectionSplitter,
)


LOCAL_PROFILE_DOCUMENTS = (
    "profile.md",
    "experience.md",
    "projects.md",
    "education.md",
    "academic-progress.md",
    "skills.md",
    "github.md",
)


def create_chat_model(settings: Settings) -> BaseChatModel:
    return ChatGoogleGenerativeAI(
        model=settings.gemini_chat_model,
        google_api_key=settings.google_api_key,
        max_retries=1,
    )


def create_embeddings(settings: Settings) -> GoogleGenerativeAIEmbeddings:
    return GoogleGenerativeAIEmbeddings(
        model=settings.gemini_embedding_model,
        google_api_key=settings.google_api_key,
        output_dimensionality=settings.embedding_dimensions,
    )


def create_agent_runtime(settings: Settings, *, index_documents: bool = False) -> tuple[MongoAtlasIndex, object, IndexingReport]:
    index, indexer, retriever = create_retrieval_runtime(settings)

    try:
        indexing_report = indexer.ensure_indexed() if index_documents else IndexingReport(False, 0, 0)
        agent = None if index_documents else create_agent(retriever, create_chat_model(settings))
    except Exception:
        index.close()
        raise

    return index, agent, indexing_report


def data_directory() -> Path:
    return Path(__file__).resolve().parents[2] / "data"


def _profile_source() -> tuple[LocalMarkdownSource, tuple[str, ...]]:
    directory = data_directory()
    document_paths = LOCAL_PROFILE_DOCUMENTS + tuple(
        path.name
        for path in sorted(directory.glob("project-*.md"))
        if path.is_file()
    )
    return LocalMarkdownSource(directory), document_paths


def create_full_context_agent_runtime(settings: Settings):
    source, document_paths = _profile_source()
    return create_full_context_agent(source.load(document_paths), create_chat_model(settings))


def create_retrieval_runtime(settings: Settings) -> tuple[MongoAtlasIndex, DocumentationIndexer, DocumentationRetriever]:
    index = MongoAtlasIndex(
        settings,
        create_embeddings(settings),
        embedding_id=f"{settings.gemini_embedding_model}:{settings.embedding_dimensions}",
    )

    try:
        source, document_paths = _profile_source()
        splitter = MarkdownSectionSplitter()
        fallback_documents = splitter.split(source.load(document_paths))
        indexer = DocumentationIndexer(source, splitter, index, paths=document_paths)
        retriever = DocumentationRetriever(index, fallback_documents)
    except Exception:
        index.close()
        raise

    return index, indexer, retriever
