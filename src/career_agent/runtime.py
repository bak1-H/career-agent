from __future__ import annotations

from pathlib import Path

from langchain_core.language_models import BaseChatModel
from langchain_google_genai import ChatGoogleGenerativeAI, GoogleGenerativeAIEmbeddings

from career_agent.adapters.mongo_atlas import MongoAtlasIndex
from career_agent.config import Settings
from career_agent.graph import create_agent
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
    "skills.md",
)


def create_chat_model(settings: Settings) -> BaseChatModel:
    return ChatGoogleGenerativeAI(
        model=settings.gemini_chat_model,
        google_api_key=settings.google_api_key,
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


def create_retrieval_runtime(settings: Settings) -> tuple[MongoAtlasIndex, DocumentationIndexer, DocumentationRetriever]:
    index = MongoAtlasIndex(
        settings,
        create_embeddings(settings),
        embedding_id=f"{settings.gemini_embedding_model}:{settings.embedding_dimensions}",
    )

    try:
        data_directory = Path(__file__).resolve().parents[2] / "data"
        document_paths = LOCAL_PROFILE_DOCUMENTS + tuple(
            path.name
            for path in sorted(data_directory.glob("project-*.md"))
            if path.is_file()
        )
        source = LocalMarkdownSource(data_directory)
        splitter = MarkdownSectionSplitter()
        fallback_documents = splitter.split(source.load(document_paths))
        indexer = DocumentationIndexer(source, splitter, index, paths=document_paths)
        retriever = DocumentationRetriever(index, fallback_documents)
    except Exception:
        index.close()
        raise

    return index, indexer, retriever
