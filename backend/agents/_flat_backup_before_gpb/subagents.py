"""Субагенты: изолированные дочерние запуски через tool `subagent`."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Mapping, Optional, Sequence, Union
import os
import re

from backend.agents.chain import _parse_positive_int, parse_agent_ids
from backend.agents.config import resolve_recursion_limit
from backend.mcp.types import McpToolInfo
from backend.settings.logging import get_logger

log = get_logger(__name__)

NATIVE_SERVER_ID = "__astra_native__"
SUBAGENT_TOOL_NAME = "subagent"
SELF_SUBAGENT_TYPE = "self"
MAX_SUBAGENTS = 10
MAX_SUBAGENTS_CAP = 50
MAX_SUBAGENT_DEPTH = 3


@dataclass
class SubagentOutcome:
    """Результат изолированного субагента: текст + опциональный RAG-трейс для UI."""

    text: str
    document_search: Optional[Dict[str, Any]] = None


SubagentExecutor = Callable[..., Awaitable[Union[str, SubagentOutcome]]]


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


SubagentExecutor = Callable[..., Awaitable[str]]


@dataclass
class AgentSubagentsConfig:
    enabled: bool = False
    allow_self: bool = True
    agent_ids: List[int] = field(default_factory=list)
    # Снимок имён на момент сохранения карточки — чтобы получатель шаринга /
    # галереи видел названия, даже если сами субагенты ему недоступны в списке.
    agent_names: Dict[int, str] = field(default_factory=dict)
    # Обязательные по тегам: агенты с любым из этих тегов вызываются кодом
    # до ответа родителя (required_subagents.py). required_only - родитель
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


def short_agent_label(label: str) -> str:
    """Убрать хвост « - description» из подписи для UI."""
    text = str(label or "").strip()
    if " - " in text:
        return text.split(" - ", 1)[0].strip() or text
    return text


@dataclass
class SubagentRunContext:
    parent_agent_id: Optional[int]
    parent_profile: Dict[str, Any]
    user: Optional[dict]
    user_id: Optional[str]
    depth: int = 0
    remaining_steps: int = 50
    executor: Optional[SubagentExecutor] = None
    # Вложения сообщения пользователя - для
    # плагинов ребёнка. Явно, а не через tool_context: у того глобальный
    # fallback, и файл мог бы прийти из чужого запроса.
    inline_attachments: Optional[List[Any]] = None
    # Имена субагентов (id → подпись) для UI-карточек tool subagent.
    agent_names: Dict[int, str] = field(default_factory=dict)
    # RAG-трейс последнего вызова субагента — agent_loop кладёт в mcp_tool_end.
    last_document_search: Optional[Dict[str, Any]] = None
    # Вопрос пользователя дословно: ребёнок получает его рядом с заданием
    # родителя (subagent_question_for_child).
    user_question: Optional[str] = None
    # Ответы детей этого хода: номер метки [[ОТВЕТ N]] → {"name", "text"}.
    answers: Dict[int, Dict[str, str]] = field(default_factory=dict)
    # Метка последнего ответа: цикл дописывает её к tool-результату для модели.
    pending_answer_no: Optional[int] = None


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


def resolve_subagent_target(
    subagent_type: str,
    *,
    parent_agent_id: Optional[int],
    config: AgentSubagentsConfig,
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
            return None
        if aid in config.agent_ids:
            return aid
    return None


def build_subagent_tools(
    config: AgentSubagentsConfig,
    *,
    parent_agent_id: Optional[int],
    agent_names: Mapping[int, str],
) -> List[McpToolInfo]:
    if not config.enabled:
        return []
    enum_values: List[str] = []
    descriptions: List[str] = []
    if config.allow_self and parent_agent_id is not None:
        enum_values.append(SELF_SUBAGENT_TYPE)
        name = agent_names.get(parent_agent_id) or "self"
        descriptions.append(
            f"- {SELF_SUBAGENT_TYPE}: spawn {name} in an isolated context"
        )
    for aid in config.agent_ids:
        st = subagent_type_for_agent_id(aid)
        enum_values.append(st)
        name = agent_names.get(aid) or f"Agent {aid}"
        descriptions.append(f"- {st}: delegate to {name}")
    if not enum_values:
        return []
    desc = (
        "Spawn an isolated subagent to handle a focused subtask. "
        "Its full answer returns with a marker like [[ОТВЕТ 1]]: put the marker "
        "on its own line in your answer to show that answer to the user verbatim.\n"
        "If the result contains :::artifact blocks (diagrams, charts, presentations, "
        "HTML) or download links, reproduce them in your final answer VERBATIM, "
        "unchanged - they are rendered for the user; do not retell them as text.\n"
        + "\n".join(descriptions)
    )
    return [
        McpToolInfo(
            server_id=NATIVE_SERVER_ID,
            name=SUBAGENT_TOOL_NAME,
            qualified_name=SUBAGENT_TOOL_NAME,
            description=desc,
            parameters={
                "type": "object",
                "properties": {
                    "subagent_type": {
                        "type": "string",
                        "enum": enum_values,
                        "description": "Which subagent to spawn",
                    },
                    "prompt": {
                        "type": "string",
                        "description": "Focused task for the subagent",
                    },
                },
                "required": ["subagent_type", "prompt"],
            },
        )
    ]


async def execute_subagent_tool(
    arguments: Dict[str, Any],
    *,
    ctx: SubagentRunContext,
    config: AgentSubagentsConfig,
) -> str:
    if ctx.depth >= MAX_SUBAGENT_DEPTH:
        return f"Subagent depth limit ({MAX_SUBAGENT_DEPTH}) reached."
    if ctx.remaining_steps <= 0:
        return "Subagent step budget exhausted."
    subagent_type = str(arguments.get("subagent_type") or "").strip()
    prompt = str(arguments.get("prompt") or arguments.get("task") or "").strip()
    if not prompt:
        return "Subagent prompt is required."
    target_id = resolve_subagent_target(
        subagent_type,
        parent_agent_id=ctx.parent_agent_id,
        config=config,
    )
    if target_id is None:
        return f"Unknown or disallowed subagent_type: {subagent_type!r}"
    if ctx.executor is None:
        return "Subagent executor is not configured."
    # Через tool subagent ходят только вызовы по решению модели: обязательные
    # (по тегам) идут мимо него, в required_subagents.py.
    log.debug(
        "[subagent] ВЫЗОВ ПО ВЫБОРУ РОДИТЕЛЯ: %s → agent_id=%s глубина=%s prompt=«%s»",
        subagent_type,
        target_id,
        ctx.depth + 1,
        prompt[:120].replace("\n", " "),
    )
    try:
        raw = await ctx.executor(
            target_agent_id=target_id,
            prompt=prompt,
            parent_profile=ctx.parent_profile,
            user=ctx.user,
            user_id=ctx.user_id,
            depth=ctx.depth + 1,
            remaining_steps=ctx.remaining_steps,
            inline_attachments=ctx.inline_attachments,
            user_question=ctx.user_question,
        )
        if isinstance(raw, SubagentOutcome):
            ctx.last_document_search = raw.document_search
            text = raw.text
        else:
            ctx.last_document_search = None
            text = str(raw or "")
        _remember_subagent_answer(ctx, target_id, text)
        return text
    except Exception as exc:
        # Строка «Subagent error» уезжала в UI с success=true. Исключение
        # ловит agent_loop: он проставит failure и напечатает traceback,
        # здесь - только адрес сбоя.
        ctx.last_document_search = None
        log.error("Subagent execution failed target=%s: %s", target_id, exc)
        raise


# --- Ответы субагентов в итоговом ответе родителя ---------------------------
#
# Родитель получает ответ ребёнка текстом tool-результата и пишет итог сам.
# Отчёт ребёнка он при этом перепечатывает: ужимает, теряет разметку (имена
# файлов в ```...``` превращались в курсив), на длинном отчёте тратит лишнюю
# минуту. Поэтому каждый ответ ребёнка получает метку [[ОТВЕТ N]]: родитель
# ставит её в свой ответ, код подставляет текст ребёнка как есть.
#
# Решает по-прежнему родитель: вставить отчёт целиком, собрать единый ответ
# из пяти своими словами или взять из ответа пару цифр. Меток не поставил -
# ответ такой же, как без этого механизма. Артефакты внутри вставленного
# ответа доезжают как есть; страховка _carry_subagent_artifacts видит их
# identifier в ответе и второй раз не дописывает.
SUBAGENT_ANSWER_MARK = "[[ОТВЕТ {n}]]"
# Модель пишет метку не всегда ровно: «[[Ответ 1]]», «[[ОТВЕТ №1]]»,
# «[[ОТВЕТ 1:]]». Номер - первое число внутри скобок.
_ANSWER_MARK_RE = re.compile(
    r"\[\[\s*ОТВЕТ\b[^\]\d]{0,40}(\d{1,3})[^\]]{0,80}\]\]", re.IGNORECASE
)
# Вопрос пользователя ребёнку - целиком, но не простыню вставленного текста.
_QUESTION_MAX_CHARS = 8000
_NUMBER_RE = re.compile(r"\d+(?:[.,]\d+)?")

SUBAGENT_RULES = """РАБОТА С СУБАГЕНТАМИ (инструмент subagent)
- В поле prompt пиши задачу для субагента. Вопрос пользователя система передаёт ему дословно сама. Не навязывай субагенту структуру ответа: у него своя инструкция. Нужные ему данные и своё пояснение пиши в prompt.
- Каждый ответ субагента приходит с меткой вида [[ОТВЕТ 1]]. Чтобы показать пользователю ответ субагента целиком и без изменений, поставь эту метку отдельной строкой в своём ответе - система подставит полный текст. Такой ответ не перепечатывай сам.
- Пользователь просил ровно то, что делает субагент (отчёт, анализ, презентацию, график, документ), - поставь его метку и ниже допиши только своё: расхождения, замечания, следующий шаг, если они есть.
- Субагентов несколько - собери единый ответ. Цифры, таблицы, статусы и ссылки на документы переноси точно; то, что нужно показать дословно, вставляй меткой.
- Артефакты (:::artifact - презентации, схемы, графики) и ссылки на файлы из ответов субагентов не пересказывай текстом: они попадут к пользователю через метку или будут добавлены автоматически."""

def subagent_question_for_child(user_question: Optional[str], task: str) -> str:
    """Задание ребёнку: вопрос пользователя дословно + задание родителя.

    Родитель пишет ребёнку своими словами и навязывает свою структуру
    (сфокусируйся на 1)…4), дай резюме) - ребёнок отвечал на неё, а не на
    вопрос. Вопрос уже есть в задании - не дублируем.
    """
    question = (user_question or "").strip()
    if not question:
        return task
    if len(question) > _QUESTION_MAX_CHARS:
        question = question[:_QUESTION_MAX_CHARS] + " …"
    if " ".join(question.split()).lower() in " ".join((task or "").split()).lower():
        return task
    return f"Вопрос пользователя: {question}\n\nЗадание от главного агента: {task}"

def _remember_subagent_answer(
    ctx: SubagentRunContext, target_id: int, text: str
) -> None:
    if not (text or "").strip():
        return
    n = len(ctx.answers) + 1
    name = short_agent_label(ctx.agent_names.get(int(target_id)) or f"Agent {target_id}")
    ctx.answers[n] = {"name": name, "text": text.strip()}
    ctx.pending_answer_no = n

def subagent_result_for_model(ctx: Optional[SubagentRunContext], content: str) -> str:
    """Tool-результат для модели родителя: метка + ответ ребёнка.

    Только для модели: в карточку субагента в чате уходит ответ без метки.
    """
    n = getattr(ctx, "pending_answer_no", None) if ctx is not None else None
    if not n:
        return content
    ctx.pending_answer_no = None
    mark = SUBAGENT_ANSWER_MARK.format(n=n)
    name = (ctx.answers.get(n) or {}).get("name") or "субагент"
    return (
        f"{mark} - ответ субагента «{name}». Чтобы показать его пользователю "
        f"целиком и без изменений, поставь в свой ответ строку {mark}.\n\n{content}"
    )

def append_subagent_rules(system_prompt: Optional[str]) -> str:
    """Правила работы с субагентами - в конец системного промпта родителя."""
    base = (system_prompt or "").rstrip()
    return f"{base}\n\n{SUBAGENT_RULES}" if base else SUBAGENT_RULES

def expand_subagent_answers(text: str, ctx: Optional[SubagentRunContext]) -> str:
    """Подставить ответы детей вместо меток [[ОТВЕТ N]] в итог родителя."""
    answers = getattr(ctx, "answers", None) or {}
    src = str(text or "")
    if not answers:
        return src
    used: List[int] = []
    unknown: List[str] = []

    def _sub(m: "re.Match[str]") -> str:
        n = int(m.group(1))
        ans = answers.get(n)
        if not ans:
            unknown.append(m.group(0))
            return ""
        used.append(n)
        return f"\n\n{ans['text']}\n\n"

    out = _ANSWER_MARK_RE.sub(_sub, src).strip()
    fallback = False
    if not out:
        # Родитель ничего не написал (сбой, пустой ответ) - работа детей не
        # должна пропасть: отдаём их ответы как есть.
        fallback = True
        items = list(answers.values())
        out = (
            items[0]["text"]
            if len(items) == 1
            else "\n\n".join(f"**▸ {a['name']}**\n\n{a['text']}" for a in items)
        )
    # Контроль пересказа: сколько чисел из НЕвставленных ответов не дошло до
    # итога. Только лог - видно, где родитель ужал отчёт.
    lost = total = 0
    for n, ans in answers.items():
        if n in used or fallback:
            continue
        nums = set(_NUMBER_RE.findall(ans["text"]))
        total += len(nums)
        lost += len(nums - set(_NUMBER_RE.findall(out)))
    log.debug(
        "[SUBAGENT-MERGE] ответов=%s вставлено меткой=%s неизвестных меток=%s "
        "пустой итог→ответы детей=%s | в пересказанных потеряно чисел: %s из %s",
        len(answers),
        sorted(set(used)),
        unknown,
        "да" if fallback else "нет",
        lost,
        total,
    )
    return out


async def execute_native_tool(
    tool_info: McpToolInfo,
    arguments: Dict[str, Any],
    *,
    subagent_ctx: Optional[SubagentRunContext] = None,
    subagent_config: Optional[AgentSubagentsConfig] = None,
) -> str:
    if tool_info.server_id != NATIVE_SERVER_ID:
        return f"Unknown native tool server: {tool_info.server_id}"
    if tool_info.name == SUBAGENT_TOOL_NAME:
        if subagent_ctx is None or subagent_config is None:
            return "Subagents are not enabled for this run."
        args = arguments if isinstance(arguments, dict) else {}
        return await execute_subagent_tool(
            args, ctx=subagent_ctx, config=subagent_config
        )
    return f"Unknown native tool: {tool_info.name}"


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
        st, parent_agent_id=parent_agent_id, config=config
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
