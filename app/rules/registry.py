from __future__ import annotations

import json
from pathlib import Path

from app.core.config import config
from app.core.models import RuleSection, Rulebook, SystemPack, PlayMode


BUILTIN_PACKS: list[SystemPack] = [
    SystemPack(
        name="d20 Fantasy Core",
        slug="d20-fantasy-core",
        description=(
            "A generic fantasy d20 rules framework for narrative and rules-driven "
            "campaign play. Designed as the first public rules-native pack."
        ),
        default_play_mode=PlayMode.RULES,
        recommended_rulebook_slug="d20-fantasy-core",
        author="RP Utility",
        version="0.1",
        is_builtin=True,
    )
]


def list_system_packs() -> list[SystemPack]:
    return BUILTIN_PACKS[:]


def get_system_pack(slug: str) -> SystemPack | None:
    for pack in BUILTIN_PACKS:
        if pack.slug == slug:
            return pack
    return None


def _rules_dir() -> Path:
    path = Path(config.rules_dir)
    path.mkdir(parents=True, exist_ok=True)
    return path


def list_rulebooks() -> list[Rulebook]:
    rulebooks: list[Rulebook] = []
    for path in sorted(_rules_dir().glob("*.json")):
        rb = load_rulebook_from_file(path)
        if rb:
            rulebooks.append(rb)
    return rulebooks


def load_rulebook_from_file(path: str | Path) -> Rulebook | None:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return None
    sections = [
        RuleSection(
            title=s.get("title", "Untitled Section"),
            content=s.get("content", ""),
            tags=[str(t) for t in s.get("tags", [])],
            priority=int(s.get("priority", 0)),
        )
        for s in data.get("sections", [])
        if s.get("content")
    ]
    return Rulebook(
        name=data.get("name", Path(path).stem),
        slug=data.get("slug", Path(path).stem.lower().replace(" ", "-")),
        description=data.get("description", ""),
        system_pack=data.get("system_pack"),
        author=data.get("author", ""),
        version=data.get("version", "1.0"),
        is_builtin=bool(data.get("is_builtin", False)),
        sections=sections,
    )

