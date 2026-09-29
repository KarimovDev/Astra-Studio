"""Имена субагентов: подпись для модели родителя и для карточек в чате."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence

from backend.agents.subagents.settings import (
    AgentSubagentsConfig,
    parse_agent_names_map,
    resolve_subagent_target,
)
from backend.settings.logging import get_logger

log = get_logger(__name__)


def short_agent_label(label: str) -> str:
    """Убрать хвост « - description» из подписи для UI."""
    text = str(label or "").strip()
    if " - " in text:
        return text.split(" - ", 1)[0].strip() or text
    return text


def resolve_subagent_display_name(
    arguments: Mapping[str, Any],
    *,
    parent_agent_id: Optional[int],
    config: AgentSubagentsConfig,
    agent_names: Mapping[int, str],
) -> Optional[str]:
    """Короткое имя субагента для UI-карточки (не agent_N)."""
    existing = str(arguments.get("agent_name") or "").strip()
    if existing:
        return short_agent_label(existing)
    st = str(arguments.get("subagent_type") or "").strip()
    target = resolve_subagent_target(
        st, parent_agent_id=parent_agent_id, config=config, agent_names=agent_names
    )
    if target is None:
        return None
    label = agent_names.get(int(target))
    if not label:
        return None
    return short_agent_label(label)


def with_subagent_display_name(
    arguments: Optional[Dict[str, Any]],
    *,
    parent_agent_id: Optional[int],
    config: Optional[AgentSubagentsConfig],
    agent_names: Optional[Mapping[int, str]] = None,
) -> Dict[str, Any]:
    """Добавить agent_name в args tool subagent для карточки в чате."""
    args = dict(arguments or {})
    if config is None:
        return args
    names = agent_names or config.agent_names
    display = resolve_subagent_display_name(
        args,
        parent_agent_id=parent_agent_id,
        config=config,
        agent_names=names,
    )
    if display:
        args["agent_name"] = display
    return args


async def load_subagent_agent_names(
    agent_ids: Sequence[int],
    *,
    user_id: Optional[str],
    snapshot_names: Optional[Mapping[int, str]] = None,
) -> Dict[int, str]:
    if not agent_ids:
        return {}
    snap = parse_agent_names_map(snapshot_names) if snapshot_names else {}
    out: Dict[int, str] = {}
    try:
        from backend.database.init_db import get_agent_repository

        repo = get_agent_repository()
        if repo is None:
            return dict(snap)
        live: Dict[int, str] = {}
        if hasattr(repo, "get_agent_names_map"):
            live = await repo.get_agent_names_map(list(agent_ids))
        for aid in agent_ids:
            key = int(aid)
            ag = await repo.get_agent(key, user_id)
            if ag and ag.name:
                label = str(ag.name).strip()
                # Родитель выбирает ребёнка по этой подписи - и только по ней.
                # Одно имя не говорит, у кого таблица, а кто строит графики;
                # без описания модель либо угадывает, либо зовёт всех подряд.
                desc = " ".join(str(getattr(ag, "description", "") or "").split())
                if desc:
                    label = f"{label} - {desc[:200]}"
                out[key] = label
            elif key in live:
                out[key] = live[key]
            elif key in snap:
                out[key] = snap[key]
        return out
    except Exception:
        log.exception("load_subagent_agent_names")
        return {**snap, **out}


async def enrich_agents_subagent_names(agents: Sequence[Any]) -> None:
    """В config.subagents.agent_names подставить актуальные имена из БД (для UI)."""
    if not agents:
        return
    try:
        from backend.database.init_db import get_agent_repository

        repo = get_agent_repository()
        if repo is None or not hasattr(repo, "get_agent_names_map"):
            return
        needed: List[int] = []
        seen = set()
        for agent in agents:
            cfg = getattr(agent, "config", None)
            if not isinstance(cfg, dict):
                continue
            sub = cfg.get("subagents")
            if not isinstance(sub, dict):
                continue
            for raw_id in sub.get("agent_ids") or []:
                try:
                    aid = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if aid > 0 and aid not in seen:
                    seen.add(aid)
                    needed.append(aid)
        if not needed:
            return
        live = await repo.get_agent_names_map(needed)
        for agent in agents:
            cfg = getattr(agent, "config", None)
            if not isinstance(cfg, dict):
                continue
            sub = cfg.get("subagents")
            if not isinstance(sub, dict):
                continue
            ids: List[int] = []
            for raw_id in sub.get("agent_ids") or []:
                try:
                    aid = int(raw_id)
                except (TypeError, ValueError):
                    continue
                if aid > 0:
                    ids.append(aid)
            if not ids:
                continue
            snap = parse_agent_names_map(sub.get("agent_names"))
            merged: Dict[int, str] = {}
            for aid in ids:
                label = live.get(aid) or snap.get(aid)
                if label:
                    merged[aid] = label
            if not merged:
                continue
            next_sub = dict(sub)
            next_sub["agent_names"] = {str(k): v for k, v in merged.items()}
            next_cfg = dict(cfg)
            next_cfg["subagents"] = next_sub
            agent.config = next_cfg
    except Exception:
        log.exception("enrich_agents_subagent_names")
