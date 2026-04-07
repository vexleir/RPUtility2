from __future__ import annotations

from app.core.models import Campaign, CampaignScene, PlayMode, Session, StyleGuide
from app.campaigns.scene_prompter import build_scene_messages
from app.rules.registry import get_system_pack, list_rulebooks


def test_session_model_supports_play_mode_and_flags():
    session = Session(
        name="Rules Test",
        character_name="Guide",
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
        feature_flags={"rules_mode": True},
    )

    assert session.play_mode == PlayMode.RULES
    assert session.system_pack == "d20-fantasy-core"
    assert session.feature_flags["rules_mode"] is True


def test_campaign_model_supports_system_pack_and_flags():
    campaign = Campaign(
        name="Bramblefork",
        play_mode=PlayMode.RULES,
        system_pack="d20-fantasy-core",
        feature_flags={"rules_mode": True, "demo_campaign": True},
        style_guide=StyleGuide(prose_style="atmospheric", tone="grounded"),
    )

    assert campaign.play_mode == PlayMode.RULES
    assert campaign.system_pack == "d20-fantasy-core"
    assert campaign.feature_flags["demo_campaign"] is True


def test_builtin_d20_system_pack_and_rulebook_are_available():
    pack = get_system_pack("d20-fantasy-core")
    assert pack is not None
    assert pack.slug == "d20-fantasy-core"

    rulebooks = list_rulebooks()
    assert any(rb.slug == "d20-fantasy-core" for rb in rulebooks)


def test_rules_mode_scene_prompt_includes_system_pack_guidance():
    class DummyCampaign:
        play_mode = PlayMode.RULES
        system_pack = "d20-fantasy-core"
        style_guide = StyleGuide(prose_style="atmospheric", tone="grounded")

    class DummyPC:
        name = "The Wayfarer"
        appearance = ""
        personality = ""
        background = ""
        wants = ""
        fears = ""
        dev_log = []

    scene = CampaignScene(campaign_id="c", scene_number=1, title="Arrival", location="Bramblefork")
    messages = build_scene_messages(
        campaign=DummyCampaign(),
        player_character=DummyPC(),
        world_facts=[],
        npcs_in_scene=[],
        active_threads=[],
        chronicle=[],
        places=[],
        factions=[],
        npc_relationships=[],
        all_world_npcs=[],
        allow_unselected_npcs=False,
        scene=scene,
        user_message="I ask the reeve what happened.",
    )

    system = messages[0]["content"]
    assert "SYSTEM PACK: d20 Fantasy Core".upper() in system.upper()
    assert "CORE RULES" in system
    assert "Checks and Difficulty" in system
