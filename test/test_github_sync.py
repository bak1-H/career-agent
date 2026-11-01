import unittest
from unittest.mock import patch

from career_agent import github_sync
from career_agent.retrieval import MarkdownSectionSplitter
from langchain_core.documents import Document


def repository(name, fork=False, archived=False, description=None):
    return {
        "name": name,
        "fork": fork,
        "archived": archived,
        "description": description,
        "pushed_at": "2026-10-31T10:00:00Z",
        "html_url": f"https://github.com/bak1-H/{name}",
        "homepage": None,
        "languages_url": f"https://api.github.com/repos/bak1-H/{name}/languages",
    }


class GithubSyncTests(unittest.TestCase):
    def test_skips_forks_archived_profile_and_excluded_repositories(self):
        listing = [repository("career-agent", description="RAG"), repository("fork", fork=True), repository("old", archived=True), repository("bak1-H"), repository("rpa-duoc")]
        responses = {"languages": {"Python": 900, "Dockerfile": 100}}
        with patch.object(github_sync, "_get", side_effect=lambda url: responses["languages"] if url.endswith("/languages") else listing):
            selected = github_sync.fetch_repositories()
        self.assertEqual([item["name"] for item in selected], ["career-agent"])

    def test_renders_one_small_section_per_repository(self):
        repositories = [{**repository("career-agent", description="RAG"), "languages": {"Python": 900, "Dockerfile": 100}}, {**repository("pedidos"), "languages": {}}]
        markdown = github_sync.render_markdown(repositories)
        self.assertIn("## Repositorio career-agent", markdown)
        self.assertIn("Python (90%), Dockerfile (10%)", markdown)
        self.assertIn("Sin descripción en GitHub.", markdown)
        chunks = MarkdownSectionSplitter().split([Document(page_content=markdown, metadata={"source": "data/github.md"})])
        self.assertTrue(all(len(chunk.page_content) < 1500 for chunk in chunks))


if __name__ == "__main__":
    unittest.main()
