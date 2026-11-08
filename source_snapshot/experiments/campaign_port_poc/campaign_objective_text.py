"""Split HoMM3 scenario objective prose into Olden Era quest-log bullets.

Vanilla Story maps put a short LocKit title on the parent quest ``name`` and
checklist lines on each visible subquest ``name`` (see ``quest_sub_M*`` in
``Lang/*/texts/campaign.json``). Empty subquest ``name`` / ``desc`` strings
resolve as player-visible ``LOC:`` placeholders.

Menu scenario blurbs still use the clipped ``*_description`` budget (172).
Quest-log bullets intentionally do not use that menu clip.
"""

from __future__ import annotations

import re

_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+")
_HOWEVER_PREFIX = re.compile(r"^(However|Also|Additionally),\s+", re.IGNORECASE)
_BUT_SPLIT = re.compile(r",\s*but\s+", re.IGNORECASE)
_WITHOUT_LOSING = re.compile(r",\s*without losing\s+", re.IGNORECASE)


def objective_obj_sid(mission_id: str, index: int) -> str:
    if index < 1:
        raise ValueError(f"objective bullet index must be >= 1, got {index}")
    return f"{mission_id}_main_goal_obj_{index}"


def clean_objective_bullet(text: str) -> str:
    one = " ".join((text or "").split()).strip()
    if not one:
        return ""
    one = _HOWEVER_PREFIX.sub("", one)
    if one.endswith("..."):
        one = one[:-3].rstrip()
    one = one.rstrip(" .")
    if not one:
        return ""
    return one[0].upper() + one[1:]


def split_objective_bullets(text: str) -> list[str]:
    """Return checklist-sized objective attributes from full scenario prose."""
    one = " ".join((text or "").split()).strip()
    if not one:
        return []

    sentences = [part.strip() for part in _SENTENCE_SPLIT.split(one) if part.strip()]
    if not sentences:
        sentences = [one]

    pieces: list[str] = []
    for sentence in sentences:
        sentence = _HOWEVER_PREFIX.sub("", sentence).strip()
        if not sentence:
            continue

        without = _WITHOUT_LOSING.search(sentence)
        if without is not None and without.start() >= 24:
            left = sentence[: without.start()].strip()
            right = "Do not lose " + sentence[without.end() :].strip()
            pieces.extend(part for part in (left, right) if part)
            continue

        if len(sentence) > 40 and _BUT_SPLIT.search(sentence):
            left, right = _BUT_SPLIT.split(sentence, maxsplit=1)
            left = left.strip()
            right = right.strip()
            if right:
                right = right[0].upper() + right[1:]
            pieces.extend(part for part in (left, right) if part)
            continue

        if ";" in sentence and len(sentence) > 60:
            for part in sentence.split(";"):
                part = part.strip(" .")
                if part:
                    pieces.append(part)
            continue

        pieces.append(sentence)

    bullets = [clean_objective_bullet(part) for part in pieces]
    return [bullet for bullet in bullets if bullet]


def objective_loc_rows(
    *,
    mission_id: str,
    title: str,
    full_description: str,
    menu_title_sid: str | None = None,
    menu_desc_sid: str | None = None,
    title_limit: int = 23,
    menu_desc_limit: int = 172,
) -> dict[str, str]:
    """Build LocKit rows for menu shell + quest title + objective bullets."""

    def clip(value: str, limit: int) -> str:
        one = " ".join((value or "").split())
        if len(one) <= limit:
            return one
        return one[: limit - 3].rstrip() + "..."

    title_one = " ".join((title or mission_id).split())
    full_one = " ".join((full_description or title_one).split())
    bullets = split_objective_bullets(full_one)
    if not bullets:
        bullets = [clean_objective_bullet(full_one) or title_one]

    rows: dict[str, str] = {
        f"{mission_id}_intro": "Briefing",
        f"{mission_id}_main_goal": clip(title_one, title_limit),
        # Kept for older maps / preflight that still reference parent desc SID.
        # New quest scripts leave parent desc null and use obj_* bullets instead.
        f"{mission_id}_main_goal_desc": bullets[0],
    }
    for index, bullet in enumerate(bullets, start=1):
        rows[objective_obj_sid(mission_id, index)] = bullet

    if menu_title_sid:
        rows[menu_title_sid] = clip(title_one, title_limit)
    if menu_desc_sid:
        rows[menu_desc_sid] = clip(full_one, menu_desc_limit)
    return rows
