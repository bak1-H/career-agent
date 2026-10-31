import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch


from career_agent import runtime


class ProjectDocumentTests(unittest.TestCase):
    def test_project_documents_reach_lexical_retrieval_without_indexing_on_startup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            data = root / "data"
            data.mkdir()
            filenames = runtime.LOCAL_PROFILE_DOCUMENTS + (
                "project-zeta.md",
                "project-alpha.md",
                "unrelated.md",
            )
            for filename in filenames:
                (data / filename).write_text(filename, encoding="utf-8")
            (data / "project-directory.md").mkdir()
            expected_sources = [
                f"data/{filename}"
                for filename in runtime.LOCAL_PROFILE_DOCUMENTS
                + ("project-alpha.md", "project-zeta.md")
            ]
            index = MagicMock()
            settings = SimpleNamespace(ollama_embedding_model="unused", ollama_base_url="http://unused")

            with (
                patch.object(runtime, "__file__", str(root / "src" / "agent" / "runtime.py")),
                patch.object(runtime, "OllamaEmbeddings"),
                patch.object(runtime, "MongoAtlasIndex", return_value=index),
                patch.object(runtime, "DocumentationRetriever") as retriever,
                patch.object(runtime, "create_agent"),
            ):
                _, _, report = runtime.create_agent_runtime(settings)

            lexical = retriever.call_args.args[1]
            index.add_documents.assert_not_called()
            index.contains.assert_not_called()
            index.ensure_ready.assert_not_called()
            self.assertEqual([item.metadata["source"] for item in lexical], expected_sources)
            self.assertFalse(report.indexed)
            index.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
