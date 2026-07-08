"""FASE 8.10: pick-conditional fruit alt-canon (light design).

When the player picks an Akuma no Mi with a canonical owner, that owner is displaced (no longer
has the fruit in the campaign world). Deliberately light: one hook per campaign, no cascade or
retroactive arc rewrite. Pure algebra: (1) offer the fruit's canonical owner as a candidate hook to
the npc_generator (WHETHER the NPC being generated IS that owner is the model's call, via
emit_npc.is_displaced_fruit_owner), and (2) build the background block for the Narrator. No I/O, no LLM.
"""
from __future__ import annotations


def active_hook_for(player_card: dict | None, npc_name: str | None) -> dict | None:
    """Candidate active_fruit_removal_hook for the npc_generator: the player's chosen fruit had a
    canonical owner. Whether the NPC being generated IS that owner is the model's call
    (emit_npc.is_displaced_fruit_owner); when it confirms, the generator itself emits the alt-canon
    (devil_fruit null + status from the hook). None when no fruit/owner/name is set."""
    pc = player_card or {}
    hook = (pc.get("removal_hook") or "").strip()
    owner = (pc.get("removal_hook_owner") or "").strip()
    if not hook or not owner or not npc_name:
        return None
    return {
        "fruit_name": (pc.get("removal_hook_fruit") or "").strip(),
        "owner_name_canon": owner,
        "hook_text": hook,
    }


def narrator_hook(player_card: dict | None, *, fruit_visible_to_narrator: bool) -> dict | None:
    """fruit_removal_hook block for the Narrator turn_state (background: the player's fruit had a
    canonical owner whose fate removed it). Only when the fruit is visible to the Narrator this
    turn. One hook per campaign."""
    pc = player_card or {}
    hook = (pc.get("removal_hook") or "").strip()
    if not hook or not fruit_visible_to_narrator:
        return None
    return {
        "fruit": (pc.get("removal_hook_fruit") or "").strip(),
        "prior_owner_fate": hook,
    }
