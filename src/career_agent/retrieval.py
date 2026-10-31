from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Protocol
import unicodedata

from langchain_core.documents import Document
from langchain_mongodb import MongoDBAtlasVectorSearch
from langchain_text_splitters import RecursiveCharacterTextSplitter

from career_agent.config import Settings


class DocumentationSource(Protocol):
    def load(self, paths: Sequence[str] | None = None) -> list[Document]:
        ...


class DocumentSplitter(Protocol):
    def split(self, documents: Sequence[Document]) -> list[Document]:
        ...


class DocumentIndex(Protocol):
    def add_documents(self, documents: list[Document]) -> object:
        ...

    def similarity_search(self, query: str, k: int) -> list[Document]:
        ...


class IndexCollection(Protocol):
    def count_documents(self, filter: dict[str, object]) -> int:
        ...


class LocalMarkdownSource:
    def __init__(self, directory: str | Path):
        self._directory = Path(directory)

    def load(self, paths: Sequence[str] | None = None) -> list[Document]:
        filenames = paths or tuple(
            path.name for path in self._directory.glob("*.md")
        )
        documents: list[Document] = []

        for filename in filenames:
            path = self._directory / filename
            if not path.is_file():
                continue
            documents.append(
                Document(
                    page_content=path.read_text(encoding="utf-8"),
                    metadata={"source": f"{self._directory.name}/{path.name}"},
                )
            )

        return documents


class LangChainDocumentSplitter:
    def __init__(self, chunk_size: int = 10_000, chunk_overlap: int = 1_000):
        self._splitter = RecursiveCharacterTextSplitter(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )

    def split(self, documents: Sequence[Document]) -> list[Document]:
        return self._splitter.split_documents(list(documents))


@dataclass(frozen=True)
class IndexingReport:
    indexed: bool
    document_count: int
    chunk_count: int


class DocumentationIndexer:
    def __init__(
        self,
        source: DocumentationSource,
        splitter: DocumentSplitter,
        index: DocumentIndex,
        collection: IndexCollection,
        paths: Sequence[str] = (),
    ):
        self._source = source
        self._splitter = splitter
        self._index = index
        self._collection = collection
        self._paths = tuple(paths)

    def ensure_indexed(self) -> IndexingReport:
        documents = self._source.load(self._paths)
        if not documents:
            raise RuntimeError("No se pudo cargar la información local del perfil.")

        chunks = self._splitter.split(documents)
        missing = [chunk for chunk in chunks if not self._collection.count_documents(
            {"source": chunk.metadata.get("source"), "text": chunk.page_content}
        )]
        if missing:
            self._index.add_documents(missing)
        return IndexingReport(
            indexed=bool(missing),
            document_count=len(documents),
            chunk_count=len(missing),
        )


class DocumentationRetriever:
    def __init__(
        self,
        index: DocumentIndex,
        fallback_documents: Sequence[Document] = (),
    ):
        self._index = index
        self._fallback_documents = tuple(fallback_documents)
        self._current_content = {}
        for document in self._fallback_documents:
            source = str(document.metadata.get("source", ""))
            if source.startswith("data/"):
                self._current_content.setdefault(source, set()).add(document.page_content)

    def search(self, query: str, limit: int = 4) -> list[Document]:
        if not _search_terms(query) or limit <= 0:
            return []

        candidate_limit = limit * 4
        lexical_documents = self._search_fallback(query, candidate_limit)
        semantic_documents = self._index.similarity_search(query, k=candidate_limit)
        semantic_documents = [document for document in semantic_documents if
            str(document.metadata.get("source", "")) not in self._current_content or
            document.page_content in self._current_content[str(document.metadata.get("source", ""))]
        ]
        scores: dict[tuple[str, str], float] = {}
        documents: dict[tuple[str, str], Document] = {}
        for ranked_documents in (lexical_documents, semantic_documents):
            seen: set[tuple[str, str]] = set()
            for document in ranked_documents:
                key = (str(document.metadata.get("source", "")), document.page_content)
                if key in seen:
                    continue
                seen.add(key)
                documents.setdefault(key, document)
                scores[key] = scores.get(key, 0.0) + 1 / (60 + len(seen))

        ranked_keys = sorted(scores, key=lambda key: -scores[key])
        return [documents[key] for key in ranked_keys[:limit]]

    def _search_fallback(self, query: str, limit: int) -> list[Document]:
        query_terms = _search_terms(query)
        if not query_terms:
            return []

        scored_documents: list[tuple[int, int, Document]] = []
        seen: set[tuple[str, str]] = set()
        for position, document in enumerate(self._fallback_documents):
            key = (str(document.metadata.get("source", "")), document.page_content)
            if key in seen:
                continue
            seen.add(key)
            document_text = " ".join(
                (
                    document.page_content,
                    str(document.metadata.get("source", "")),
                )
            )
            overlap = query_terms.intersection(_search_terms(document_text))
            if overlap:
                scored_documents.append((len(overlap), -position, document))

        scored_documents.sort(reverse=True)
        return [document for _, _, document in scored_documents[:limit]]


def _search_terms(text: str) -> set[str]:
    normalized_text = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(
        character for character in normalized_text if not unicodedata.combining(character)
    )
    tokens = set(re.findall(r"[a-z0-9]+", without_accents))
    return tokens.difference(
        {
            "a",
            "al",
            "con",
            "de",
            "del",
            "el",
            "en",
            "es",
            "esta",
            "este",
            "la",
            "las",
            "los",
            "para",
            "por",
            "que",
            "se",
            "un",
            "una",
            "y",
        }
    )


def create_vector_store(settings: Settings, collection):
    from langchain_ollama import OllamaEmbeddings

    embeddings = OllamaEmbeddings(
        model=settings.ollama_embedding_model,
        base_url=settings.ollama_base_url,
    )
    return MongoDBAtlasVectorSearch(
        embedding=embeddings,
        collection=collection,
        index_name=settings.atlas_vector_search_index_name,
        relevance_score_fn="cosine",
    )
