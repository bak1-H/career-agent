import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src" / "agente-carrera"))

import runtime


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
            client = MagicMock()
            collection = client.__getitem__.return_value.__getitem__.return_value
            collection.count_documents.return_value = 0
            vector_store = MagicMock()
            settings = SimpleNamespace(
                mongodb_uri="mongodb://unused",
                mongodb_database="unused",
                mongodb_collection="unused",
            )

            with (
                patch.object(runtime, "__file__", str(root / "src" / "agent" / "runtime.py")),
                patch.object(runtime, "MongoClient", return_value=client),
                patch.object(runtime, "create_vector_store", return_value=vector_store),
                patch.object(runtime, "DocumentationRetriever") as retriever,
                patch.object(runtime, "create_agent"),
            ):
                _, _, report = runtime.create_agent_runtime(settings)

            lexical = retriever.call_args.args[1]
            vector_store.add_documents.assert_not_called()
            collection.count_documents.assert_not_called()
            self.assertEqual([item.metadata["source"] for item in lexical], expected_sources)
            self.assertFalse(report.indexed)
            client.close.assert_not_called()


if __name__ == "__main__":
    unittest.main()
