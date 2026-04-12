from __future__ import annotations

from pathlib import Path
import shutil

import app.web.campaign_routes as routes
from app.compendium.store import CompendiumStore


def test_builtin_compendium_entries_are_available():
    store = CompendiumStore()
    entries = store.list_all(system_pack="d20-fantasy-core")
    slugs = {entry.slug for entry in entries}

    assert "dash" in slugs
    assert "poisoned" in slugs
    assert "bless" in slugs
    assert "help" in slugs
    assert "second-wind" in slugs
    assert "healing-word" in slugs
    assert "disengage" in slugs
    assert "cure-wounds" in slugs
    assert "magic-missile" in slugs
    assert "shield" in slugs
    assert "leather-armor" in slugs
    assert "healing-wand" in slugs


def test_compendium_store_save_and_get_custom_entry(monkeypatch):
    target_dir = Path.cwd() / ".tmp" / "compendium-store-test"
    shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(routes.config, "compendium_dir", str(target_dir))
    store = CompendiumStore()
    entry = routes.CompendiumEntry(
        slug="healing-word",
        name="Healing Word",
        category="spell",
        system_pack="d20-fantasy-core",
        description="A quick healing spell.",
        rules_text="Restore a small amount of HP at range.",
        action_cost="bonus_action",
        range_feet=60,
        resource_costs={"spell_slot_1": 1},
    )

    path = store.save(entry)
    loaded = store.get("healing-word", system_pack="d20-fantasy-core")

    assert Path(path).exists()
    assert loaded is not None
    assert loaded.name == "Healing Word"
    assert loaded.action_cost == "bonus_action"
    assert loaded.range_feet == 60


def test_compendium_api_save_and_list_entry(monkeypatch):
    target_dir = Path.cwd() / ".tmp" / "compendium-api-test"
    shutil.rmtree(target_dir, ignore_errors=True)
    target_dir.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(routes.config, "compendium_dir", str(target_dir))

    saved = routes.api_save_compendium_entry(
        routes.SaveCompendiumEntryRequest(
            slug="second-wind",
            name="Second Wind",
            category="action",
            system_pack="d20-fantasy-core",
            description="Recover some HP.",
            rules_text="Regain a small amount of HP.",
            action_cost="bonus_action",
            applies_conditions=[],
        )
    )
    listed = routes.api_list_compendium_entries(system_pack="d20-fantasy-core", query="Second Wind")

    assert saved["slug"] == "second-wind"
    assert saved["action_cost"] == "bonus_action"
    assert any(entry["slug"] == "second-wind" for entry in listed)
