"""Tones (writing styles) applied on top of - or instead of - a translation.

Taken from the browser extension so both behave the same.
"""
from __future__ import annotations

from typing import NamedTuple

TONE_DEFAULT = "default"
TONE_CUSTOM_PREFIX = "custom:"
MAX_CUSTOM_TONE_LENGTH = 80


class Tone(NamedTuple):
    code: str
    name: str
    hint: str
    instruction: str


class ToneInstruction(NamedTuple):
    label: str
    instruction: str


_RAW = [
    ("improve", "Improve", "Fix & polish", "Improve the writing: fix grammar, spelling and punctuation, and make it clearer and smoother. Keep the meaning, the voice and roughly the same length."),
    ("advanced", "Advanced", "Richer vocabulary", "Rewrite it with a more sophisticated, advanced vocabulary and polished sentence structure, as an articulate, well-read writer would. Keep the meaning."),
    ("formal", "Formal", "Professional", "Write it in a formal, professional register: no slang, no contractions, courteous and precise."),
    ("short", "Short", "Concise", "Make it as short and concise as possible while keeping the key meaning. Remove filler."),
    ("tribal", "Tribal", "Elders by the fire", "Write it in a tribal, ancestral voice, as an elder speaking around a fire: earthy, communal imagery (the land, the ancestors, the spirits, the hunt). Keep the meaning."),
    ("corp", "Corp", "Corporate speak", "Write it in corporate business jargon (synergy, stakeholders, bandwidth, leverage, circle back, align on deliverables). Keep the meaning."),
    ("biblical", "Biblical", "Scripture style", "Write it in the solemn style of the King James Bible: archaic phrasing (thee, thou, verily, unto), rhythmic and reverent. Keep the meaning."),
    ("viking", "Viking", "Norse warrior", "Write it as a bold, boastful Viking warrior would: fierce and proud, with references to Odin, Valhalla, glory, ships and battle. Keep the meaning."),
    ("zen", "Zen", "Calm & minimal", "Write it in a calm, serene, minimalist Zen tone: spare, mindful, peaceful, with gentle imagery. Keep the meaning."),
    ("emojify", "Emojify", "Add emojis", "Keep the text but add fitting emojis after key phrases and at the end of sentences. Do not overdo it."),
]

TONES: list[Tone] = [Tone(*row) for row in _RAW]
_BY_CODE = {t.code: t for t in TONES}


def is_custom_tone(code: str) -> bool:
    return code.startswith(TONE_CUSTOM_PREFIX)


def make_custom_tone_code(text: str) -> str:
    return TONE_CUSTOM_PREFIX + " ".join(text.split())[:MAX_CUSTOM_TONE_LENGTH]


def is_valid_tone_code(code: object) -> bool:
    if not isinstance(code, str):
        return False
    if code == TONE_DEFAULT or code in _BY_CODE:
        return True
    if not is_custom_tone(code):
        return False
    n = len(code) - len(TONE_CUSTOM_PREFIX)
    return 0 < n <= MAX_CUSTOM_TONE_LENGTH


def find_tone(code: str) -> Tone | None:
    return _BY_CODE.get(code)


def tone_name(code: str) -> str:
    if code == TONE_DEFAULT:
        return "Default"
    if is_custom_tone(code):
        return code[len(TONE_CUSTOM_PREFIX):]
    t = _BY_CODE.get(code)
    return t.name if t else code


def tone_instruction(code: str) -> ToneInstruction | None:
    """The tone line of the model prompt, or None when no tone applies."""
    if code == TONE_DEFAULT:
        return None
    if is_custom_tone(code):
        text = code[len(TONE_CUSTOM_PREFIX):]
        return ToneInstruction(
            "Custom",
            f'Write it in this custom tone/style, described by the user as: "{text}". Keep the meaning.',
        )
    t = _BY_CODE.get(code)
    return ToneInstruction(t.name, t.instruction) if t else None


def search_tones(query: str) -> list[Tone]:
    q = query.strip().lower()
    if not q:
        return list(TONES)
    starts = [t for t in TONES if t.name.lower().startswith(q)]
    contains = [t for t in TONES if not t.name.lower().startswith(q)
                and (q in t.name.lower() or q in t.hint.lower())]
    return starts + contains
