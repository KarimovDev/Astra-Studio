"""Субагенты в карточке родителя (config.subagents): разбор, лимиты, выбор цели."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Optional

from backend.agents.chain.settings import _parse_positive_int, parse_agent_ids
from backend.agents.config import resolve_recursion_limit


NATIVE_SERVER_ID = "__astra_native__"
SUBAGENT_TOOL_NAME = "subagent"
SELF_SUBAGENT_TYPE = "self"
MAX_SUBAGENTS = 10
MAX_SUBAGENTS_CAP = 50
MAX_SUBAGENT_DEPTH = 3


def _env_int(name: str, default: int, *, lo: int, hi: int) -> int:
    raw = (os.getenv(name) or "").strip()
    if not raw:
        return max(lo, min(default, hi))
    try:
        return max(lo, min(int(raw), hi))
    except ValueError:
        return max(lo, min(default, hi))


def get_max_subagents() -> int:
    """Максимум субагентов: AGENT_SUBAGENTS_MAX (ConfigMap)."""
    return _env_int("AGENT_SUBAGENTS_MAX", MAX_SUBAGENTS, lo=1, hi=MAX_SUBAGENTS_CAP)


def resolve_max_subagents(agent_profile: Optional[Mapping[str, Any]] = None) -> int:
    """Эффективный лимит субагентов: per-agent → платформенный (AGENT_SUBAGENTS_MAX)."""
    platform = get_max_subagents()
    if not isinstance(agent_profile, Mapping):
        return platform
    parsed = _parse_positive_int(agent_profile.get("max_subagents"))
    if parsed is None:
        return platform
    return max(1, min(parsed, platform))


@dataclass
class AgentSubagentsConfig:
    enabled: bool = False
    allow_self: bool = True
    agent_ids: List[int] = field(default_factory=list)
    # Снимок имён на момент сохранения карточки — чтобы получатель шаринга /
    # галереи видел названия, даже если сами субагенты ему недоступны в списке.
    agent_names: Dict[int, str] = field(default_factory=dict)
    # Обязательные по тегам: агенты с любым из этих тегов вызываются кодом
    # до ответа родителя (subagents/required.py). required_only - родитель
    # сверх них никого не зовёт.
    required_tag_ids: List[int] = field(default_factory=list)
    required_only: bool = False


def parse_agent_names_map(raw: Any) -> Dict[int, str]:
    """config.subagents.agent_names: {id|str: name} → Dict[int, str]."""
    if not isinstance(raw, Mapping):
        return {}
    out: Dict[int, str] = {}
    for key, value in raw.items():
        try:
            aid = int(key)
        except (TypeError, ValueError):
            continue
        if aid <= 0:
            continue
        label = str(value or "").strip()
        if label:
            out[aid] = label
    return out


def parse_subagents_config(
    raw: Any,
    *,
    exclude_id: Optional[int] = None,
    agent_profile: Optional[Mapping[str, Any]] = None,
) -> AgentSubagentsConfig:
    if not isinstance(raw, dict):
        return AgentSubagentsConfig()
    enabled = raw.get("enabled") is True
    allow_self = raw.get("allow_self")
    if allow_self is None:
        allow_self = raw.get("allowSelf")
    allow_self_bool = allow_self is not False
    max_sub = resolve_max_subagents(agent_profile)
    agent_ids = parse_agent_ids(
        raw.get("agent_ids"), exclude_id=exclude_id, max_agents=max_sub
    )
    required_tag_ids: List[int] = []
    for item in raw.get("required_tag_ids") or []:
        try:
            tid = int(item)
        except (TypeError, ValueError):
            continue
        if tid > 0 and tid not in required_tag_ids:
            required_tag_ids.append(tid)
    required_only = raw.get("required_only") is True
    return AgentSubagentsConfig(
        enabled=enabled,
        allow_self=allow_self_bool,
        agent_ids=agent_ids,
        agent_names=parse_agent_names_map(raw.get("agent_names")),
        required_tag_ids=required_tag_ids,
        required_only=required_only,
    )


def subagent_type_for_agent_id(agent_id: int) -> str:
    return f"agent_{int(agent_id)}"


def _subagent_name_key(label: Any) -> str:
    """Имя субагента для сравнения: без описания, регистра, кавычек и лишних пробелов."""
    text = str(label or "").split(" - ", 1)[0]
    text = text.strip().strip("«»“”„\"'`").replace("ё", "е").replace("Ё", "Е")
    return " ".join(text.split()).casefold()


def subagent_type_by_name(
    config: AgentSubagentsConfig,
    agent_names: Optional[Mapping[int, str]] = None,
) -> Dict[int, str]:
    """id субагента → его значение subagent_type: имя, если оно однозначно.

    Модель выбирает субагента по имени, а не по номеру agent_N: номер ни о
    чём не говорит, и 24.09 главный раздал задания по порядку списка -
    субагент «Раздел_2» писал раздел 9. По имени модель берёт того, чьё имя
    подходит к заданию. Имя любое; остаётся agent_N, если имени нет, если
    оно у двух субагентов одинаковое, если это «self» или само выглядит как
    agent_<число> (иначе совпало бы с номером другого субагента).
    """
    names = {**(config.agent_names or {}), **dict(agent_names or {})}
    labels: Dict[int, str] = {}
    for aid in config.agent_ids:
        short = str(names.get(aid) or "").split(" - ", 1)[0].strip()
        if short:
            labels[aid] = short
    keys = [_subagent_name_key(v) for v in labels.values()]
    out: Dict[int, str] = {}
    for aid in config.agent_ids:
        label = labels.get(aid)
        key = _subagent_name_key(label)
        looks_like_id = key.startswith("agent_") and key[6:].isdigit()
        if label and key != SELF_SUBAGENT_TYPE and not looks_like_id and keys.count(key) == 1:
            out[aid] = label
        else:
            out[aid] = subagent_type_for_agent_id(aid)
    return out


def resolve_subagent_target(
    subagent_type: str,
    *,
    parent_agent_id: Optional[int],
    config: AgentSubagentsConfig,
    agent_names: Optional[Mapping[int, str]] = None,
) -> Optional[int]:
    st = (subagent_type or "").strip()
    if st == SELF_SUBAGENT_TYPE:
        if not config.allow_self or parent_agent_id is None:
            return None
        return int(parent_agent_id)
    if st.startswith("agent_"):
        try:
            aid = int(st[6:])
        except (TypeError, ValueError):
            aid = None
        if aid is not None:
            return aid if aid in config.agent_ids else None
    # По имени (subagent_type_by_name): без учёта регистра, кавычек, «ё».
    key = _subagent_name_key(st)
    if not key:
        return None
    hits = [
        aid
        for aid, value in subagent_type_by_name(config, agent_names).items()
        if _subagent_name_key(value) == key
    ]
    return hits[0] if len(hits) == 1 else None


def subagents_from_profile(profile: Mapping[str, Any]) -> AgentSubagentsConfig:
    parent_id = profile.get("agent_id")
    exclude = int(parent_id) if parent_id is not None else None
    return parse_subagents_config(
        profile.get("subagents"),
        exclude_id=exclude,
        agent_profile=profile,
    )


def profile_recursion_limit(profile: Mapping[str, Any]) -> int:
    return resolve_recursion_limit(profile)
