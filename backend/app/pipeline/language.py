"""Campaign prose language. A ContextVar set at every entry point that loads the campaign;
writers append output_directive() to their volatile block and engine strings go through
engine_str(). The language is frozen at campaign creation.
"""
from __future__ import annotations

from contextvars import ContextVar

from .. import config

DEFAULT_LANGUAGE = "pt-br"
SUPPORTED_LANGUAGES = ("pt-br", "en")

_current: ContextVar[str] = ContextVar("campaign_language", default=DEFAULT_LANGUAGE)


def set_language(lang: str | None) -> None:
    lang = (lang or "").strip().lower()
    _current.set(lang if lang in SUPPORTED_LANGUAGES else DEFAULT_LANGUAGE)


def set_from_campaign(campaign: dict | None) -> None:
    set_language((campaign or {}).get("language"))


def current_language() -> str:
    return _current.get()


_PT_DIRECTIVE = (
    "Idioma da campanha: PT-BR. Toda prosa, diálogo e todo campo de texto visível ao "
    "jogador saem em português brasileiro."
)

_EN_DIRECTIVE = (
    "Campaign language: ENGLISH. Write ALL prose, dialogue and every player-visible text "
    "field in English. Canon terms use the official English wiki forms (Marines, Devil "
    "Fruit, Haki, berries, Log Pose). Dialogue follows English punctuation convention "
    "(double quotes), not the pt-br em-dash. This directive overrides any mention of "
    "PT-BR in the instructions above. Inputs (cards, crystals, briefings, memory) may "
    "arrive in Portuguese: use their content, but never quote Portuguese words in the "
    "output — no Portuguese word may reach the player."
)


def output_directive() -> str:
    return _EN_DIRECTIVE if current_language() == "en" else _PT_DIRECTIVE


def with_directive(addenda: str | None = None) -> str:
    """Volatile block content: optional conditional addenda followed by the directive."""
    d = output_directive()
    return f"{addenda}\n\n---\n\n{d}" if addenda else d


def prompt_file(base: str) -> str:
    """Prompt filename for the current language, falling back to the pt-br file."""
    candidate = f"{base}.{current_language()}.md"
    if (config.PROMPTS_DIR / candidate).exists():
        return candidate
    return f"{base}.{DEFAULT_LANGUAGE}.md"


_ENGINE_STRINGS: dict[str, dict[str, str]] = {
    "pt-br": {
        "uncharted_island": "Ilha desconhecida",
        "open_sea": "em mar aberto",
        "bound_for": "rumo a {name}",
        "at_location": " em {location}",
        "bounty_hunter_appeared": "Caçador de recompensa apareceu atrás do bando{where}: {who}{aff}.",
        "crew_join_request": "Pediram para entrar no bando do jogador: {names}.",
        "crew_member_joined": "{name} entrou para o bando do jogador.",
        "crew_invite_refused": "{name} recusou o convite para entrar no bando do jogador.",
        "crew_member_left": "{name} deixou o bando do jogador{why}.",
        "fallback_new_companion": "Um novo companheiro",
        "fallback_someone": "Alguém",
        "fallback_companion": "Um companheiro",
        "fallback_bounty_hunter": "um caçador de recompensa",
        "alliance_formed": "O bando selou uma aliança {kind} com {name}{hier}{where}.{extra}",
        "alliance_kind_formal": "formal",
        "alliance_kind_informal": "informal",
        "alliance_hier_subordinate": " (subordinada ao bando)",
        "alliance_hier_sovereign": " (o bando jurou a ela)",
        "alliance_broken": "A aliança com {name} foi rompida{why}{where}.",
        "fallback_other_crew": "outra crew",
        "hunter_out_of_play": "{name} — perseguidor recorrente do bando — saiu de jogo ({outcome}).",
        "hunter_evolved": "{name} cresceu como perseguidor do bando ({facet}).",
        "hunter_facet_fallback": "salto",
        "hunter_posture_shift": "A postura de {name} com o bando virou {posture}.",
        "hunter_clash": "{name} voltou a cruzar o bando.",
        "fallback_the_hunter": "O caçador",
    },
    "en": {
        "uncharted_island": "Uncharted island",
        "open_sea": "open sea",
        "bound_for": "bound for {name}",
        "at_location": " at {location}",
        "bounty_hunter_appeared": "A bounty hunter came after the crew{where}: {who}{aff}.",
        "crew_join_request": "Asked to join the player's crew: {names}.",
        "crew_member_joined": "{name} joined the player's crew.",
        "crew_invite_refused": "{name} turned down the invitation to join the player's crew.",
        "crew_member_left": "{name} left the player's crew{why}.",
        "fallback_new_companion": "A new companion",
        "fallback_someone": "Someone",
        "fallback_companion": "A companion",
        "fallback_bounty_hunter": "a bounty hunter",
        "alliance_formed": "The crew sealed a {kind} alliance with {name}{hier}{where}.{extra}",
        "alliance_kind_formal": "formal",
        "alliance_kind_informal": "informal",
        "alliance_hier_subordinate": " (subordinate to the crew)",
        "alliance_hier_sovereign": " (the crew pledged itself to them)",
        "alliance_broken": "The alliance with {name} was broken{why}{where}.",
        "fallback_other_crew": "another crew",
        "hunter_out_of_play": "{name}, a recurring pursuer of the crew, is out of play ({outcome}).",
        "hunter_evolved": "{name} grew as a pursuer of the crew ({facet}).",
        "hunter_facet_fallback": "leap",
        "hunter_posture_shift": "{name}'s stance toward the crew shifted to {posture}.",
        "hunter_clash": "{name} crossed the crew's path again.",
        "fallback_the_hunter": "The hunter",
    },
}


def engine_str(key: str, **kw) -> str:
    table = _ENGINE_STRINGS.get(current_language()) or _ENGINE_STRINGS[DEFAULT_LANGUAGE]
    template = table.get(key) or _ENGINE_STRINGS[DEFAULT_LANGUAGE][key]
    return template.format(**kw) if kw else template
