import unittest

from langchain_core.documents import Document

from career_agent.retrieval import MarkdownSectionSplitter


class MarkdownSectionSplitterTests(unittest.TestCase):
    def test_each_section_keeps_its_headings_and_source(self):
        document = Document(
            page_content="# Educación\n\n## Ingeniería\n\n- DUOC UC\n\n## Analista\n\n- Título completado",
            metadata={"source": "data/education.md"},
        )
        chunks = MarkdownSectionSplitter().split([document])
        self.assertEqual(
            [chunk.page_content for chunk in chunks],
            ["# Educación\n## Ingeniería\n- DUOC UC", "# Educación\n## Analista\n- Título completado"],
        )
        self.assertEqual({chunk.metadata["source"] for chunk in chunks}, {"data/education.md"})

    def test_text_without_headings_is_kept_whole(self):
        chunks = MarkdownSectionSplitter().split([Document(page_content="plain", metadata={"source": "data/a.md"})])
        self.assertEqual([chunk.page_content for chunk in chunks], ["plain"])


if __name__ == "__main__":
    unittest.main()
