from __future__ import annotations

import json
from pathlib import Path

from app.core.config import config
from app.core.models import RuleSection, Rulebook


def _rules_dir() -> Path:
    path = Path(config.rules_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


class RulebookStore:
    def list_all(self) -> list[Rulebook]:
        result: list[Rulebook] = []
        for path in sorted(_rules_dir().glob("*.json")):
            rb = self.get_by_path(path)
            if rb:
                result.append(rb)
        return result

    def get(self, slug: str) -> Rulebook | None:
        path = _rules_dir() / f"{slug.replace('-', '_')}.json"
        if path.exists():
            return self.get_by_path(path)
        for candidate in _rules_dir().glob("*.json"):
            rb = self.get_by_path(candidate)
            if rb and rb.slug == slug:
                return rb
        return None

    def save(self, rulebook: Rulebook) -> Path:
        path = _rules_dir() / f"{rulebook.slug.replace('-', '_')}.json"
        payload = {
            "name": rulebook.name,
            "slug": rulebook.slug,
            "description": rulebook.description,
            "system_pack": rulebook.system_pack,
            "author": rulebook.author,
            "version": rulebook.version,
            "is_builtin": rulebook.is_builtin,
            "sections": [
                {
                    "title": s.title,
                    "content": s.content,
                    "tags": s.tags,
                    "priority": s.priority,
                }
                for s in rulebook.sections
            ],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return path

    def get_by_path(self, path: str | Path) -> Rulebook | None:
        try:
            data = json.loads(Path(path).read_text(encoding="utf-8"))
        except Exception:
            return None
        return Rulebook(
            name=data.get("name", Path(path).stem),
            slug=data.get("slug", Path(path).stem.replace("_", "-")),
            description=data.get("description", ""),
            system_pack=data.get("system_pack"),
            author=data.get("author", ""),
            version=data.get("version", "1.0"),
            is_builtin=bool(data.get("is_builtin", False)),
            sections=[
                RuleSection(
                    title=s.get("title", "Untitled Section"),
                    content=s.get("content", ""),
                    tags=[str(t) for t in s.get("tags", [])],
                    priority=int(s.get("priority", 0)),
                )
                for s in data.get("sections", [])
                if s.get("content")
            ],
        )

