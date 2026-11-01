from __future__ import annotations

import json
import os
from collections import Counter
from pathlib import Path
from urllib.request import Request, urlopen


GITHUB_USER = "bak1-H"
GITHUB_API = "https://api.github.com"
MAX_REPOSITORIES = 20
EXCLUDED_REPOSITORIES = frozenset({"rpa-duoc"})
MAX_DESCRIPTION_LENGTH = 300


def _get(url: str) -> object:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "career-agent"}
    token = os.environ.get("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urlopen(Request(url, headers=headers), timeout=30) as response:
        return json.load(response)


def fetch_repositories(user: str = GITHUB_USER) -> list[dict]:
    repositories = _get(f"{GITHUB_API}/users/{user}/repos?per_page=100&sort=pushed&type=owner")
    selected = [
        repository for repository in repositories
        if not repository["fork"] and not repository["archived"] and repository["name"].lower() != user.lower()
        and repository["name"] not in EXCLUDED_REPOSITORIES
    ][:MAX_REPOSITORIES]
    for repository in selected:
        repository["languages"] = _get(repository["languages_url"])
    return selected


def _language_shares(languages: dict[str, int]) -> str:
    total = sum(languages.values())
    if not total:
        return "sin lenguajes detectados"
    return ", ".join(f"{name} ({bytes_ * 100 // total}%)" for name, bytes_ in sorted(languages.items(), key=lambda item: -item[1]) if bytes_ * 100 // total)


def render_markdown(repositories: list[dict], user: str = GITHUB_USER) -> str:
    primary = Counter(max(languages, key=languages.get) for repository in repositories if (languages := repository.get("languages")))
    top_languages = ", ".join(f"{name} ({count})" for name, count in primary.most_common(5)) or "sin datos"
    lines = [
        "# Repositorios públicos en GitHub",
        "",
        f"- Perfil: https://github.com/{user}",
        f"- Repositorios públicos propios: {len(repositories)}.",
        f"- Lenguaje principal por cantidad de repositorios: {top_languages}.",
        f"- Repositorio con actividad más reciente: {repositories[0]['name']} ({repositories[0]['pushed_at'][:10]})." if repositories else "- Sin actividad pública reciente.",
    ]
    for repository in repositories:
        description = (repository.get("description") or "Sin descripción en GitHub.").strip()[:MAX_DESCRIPTION_LENGTH]
        lines += [
            "",
            f"## Repositorio {repository['name']}",
            "",
            f"- Descripción: {description}",
            f"- Lenguajes: {_language_shares(repository.get('languages') or {})}.",
            f"- Última actividad: {repository['pushed_at'][:10]}.",
            f"- Enlace: {repository['html_url']}",
        ]
        if repository.get("homepage"):
            lines.append(f"- Sitio publicado: {repository['homepage']}")
    return "\n".join(lines) + "\n"


def sync_github(destination: Path, user: str = GITHUB_USER) -> int:
    repositories = fetch_repositories(user)
    destination.write_text(render_markdown(repositories, user), encoding="utf-8")
    return len(repositories)
