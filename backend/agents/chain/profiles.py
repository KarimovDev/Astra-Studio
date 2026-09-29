"""Цепочка: профили агентов и payload чата под каждый шаг."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from backend.agents.chain.settings import parse_agent_ids


async def resolve_agent_chain(
    primary_id: Any,
    primary_profile: Dict[str, Any],
    user_id: Optional[str],
    user: Optional[dict] = None,
) -> List[Dict[str, Any]]:
    """Загрузить профили цепочки: [primary, ...agent_ids]. Без транзитивного обхода чужих цепочек."""
    from backend.realtime.helpers import _resolve_agent_chat_params

    try:
        pid = int(primary_id) if primary_id is not None else None
    except (TypeError, ValueError):
        pid = None

    primary = dict(primary_profile) if isinstance(primary_profile, dict) else {}
    if pid is not None:
        primary["agent_id"] = pid
    chain: List[Dict[str, Any]] = [primary]
    if not pid:
        return chain

    next_ids = parse_agent_ids(
        primary.get("agent_ids"), exclude_id=pid, agent_profile=primary
    )
    if not next_ids:
        return chain

    for aid in next_ids:
        profile = await _resolve_agent_chat_params(aid, user_id, user=user)
        if not isinstance(profile, dict):
            continue
        if not (profile.get("name") or profile.get("system_prompt")):
            continue
        profile["agent_id"] = aid
        chain.append(profile)
    return chain


def prepare_step_socket_data(
    data: Optional[dict],
    profile: Dict[str, Any],
    *,
    is_first: bool,
) -> dict:
    """Копия payload чата под конкретного агента цепочки.

    MCP/плагины — из карточки шага. coding_mode и явный tool_ids UI — только у первого.
    """
    from backend.realtime.helpers import agent_mcp_tool_ids, agent_plugin_ids

    step_data = dict(data) if isinstance(data, dict) else {}
    if not is_first:
        step_data.pop("coding_mode", None)
        step_data.pop("plan_mode", None)
        step_data.pop("approved_plan", None)
        # #теги из чата отрабатывают только на первом шаге цепочки —
        # иначе одни и те же агенты вызвались бы на каждом hop.
        step_data.pop("tag_ids", None)
        if isinstance(step_data.get("message"), str):
            try:
                from backend.services.tag_mentions import strip_tag_mentions

                step_data["message"] = strip_tag_mentions(step_data["message"])
            except Exception:
                pass
        step_data["tool_ids"] = agent_mcp_tool_ids(profile)
        plugins = agent_plugin_ids(profile)
        if plugins:
            step_data["__plugin_ids__"] = plugins
        else:
            step_data.pop("__plugin_ids__", None)
        return step_data

    if not (step_data.get("tool_ids") or step_data.get("mcp_tool_ids")):
        mcp_ids = agent_mcp_tool_ids(profile)
        if mcp_ids:
            step_data["tool_ids"] = mcp_ids
    plugins = agent_plugin_ids(profile)
    if plugins:
        step_data["__plugin_ids__"] = plugins
    return step_data
