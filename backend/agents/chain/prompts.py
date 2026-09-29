"""Цепочка: что получает следующий агент и что видит пользователь."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence, Tuple


DEFAULT_CHAIN_PROMPT_TEMPLATE = (
    "Based on the following conversation and analysis from previous agents, "
    "please provide your insights:\n\n{convo}\n\n"
    "Please add your specific expertise and perspective to this discussion."
)


def format_run_buffer(
    user_message: str,
    steps: Sequence[Dict[str, Any]],
) -> str:
    """Буфер текущего хода: вопрос пользователя + ответы предыдущих агентов."""
    parts = [f"Human: {user_message.strip()}"]
    for step in steps:
        name = str(step.get("agent_name") or "Agent").strip() or "Agent"
        content = str(step.get("content") or "").strip()
        parts.append(f"AI ({name}): {content}")
    return "\n\n".join(parts)


def build_chain_user_message(
    user_message: str,
    steps: Sequence[Dict[str, Any]],
    prompt_template: str = DEFAULT_CHAIN_PROMPT_TEMPLATE,
) -> str:
    """Промпт следующего агента: Mixure-of-Agents с `{convo}`."""
    convo = format_run_buffer(user_message, steps)
    template = (
        prompt_template or DEFAULT_CHAIN_PROMPT_TEMPLATE
    ).strip() or DEFAULT_CHAIN_PROMPT_TEMPLATE
    if "{convo}" not in template:
        return f"{template}\n\n{convo}"
    return template.replace("{convo}", convo)


def format_visible_chain_content(
    steps: Sequence[Dict[str, Any]],
    *,
    hide_sequential_outputs: bool,
) -> str:
    """Текст, который видит пользователь и который уходит в историю."""
    if not steps:
        return ""
    if hide_sequential_outputs:
        return str(steps[-1].get("content") or "")
    blocks: List[str] = []
    for step in steps:
        name = str(step.get("agent_name") or "Агент").strip() or "Агент"
        content = str(step.get("content") or "").strip()
        blocks.append(f"**▸ {name}**\n\n{content}")
    return "\n\n".join(blocks).strip()


def chain_step_header(agent_name: str) -> str:
    name = (agent_name or "").strip() or "Агент"
    return f"**▸ {name}**\n\n"


def iter_chain_stream_prefixes(
    steps_so_far: Iterable[Dict[str, Any]],
    next_name: str,
    *,
    hide_sequential_outputs: bool,
) -> Tuple[str, str]:
    """Вернуть (stream_prefix, header) для текущего шага."""
    if hide_sequential_outputs:
        return "", ""
    header = chain_step_header(next_name)
    if not steps_so_far:
        return header, header
    visible = format_visible_chain_content(
        list(steps_so_far), hide_sequential_outputs=False
    )
    prefix = f"{visible}\n\n{header}" if visible else header
    return prefix, header
