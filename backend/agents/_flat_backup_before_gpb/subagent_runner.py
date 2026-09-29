"""Запуск изолированного субагента.

По умолчанию субагент изолирован и не наследует RAG родителя. Исключение —
режим «общий RAG для цепочки/субагентов» (config.shared_chain_rag головного
агента): тогда база знаний головного агента подмешивается в контекст субагента,
и этот режим наследуется вниз по всей ветке субагентов.
"""

from __future__ import annotations

import asyncio
import contextvars
import functools
import os
from typing import Any, Dict, List, Optional, Tuple

from backend.agents.config import resolve_recursion_limit
from backend.agents.step_debug import describe_limit_source, log_pre_loop
from backend.agents.subagents import (
    SubagentOutcome,
    SubagentRunContext,
    build_subagent_tools,
    load_subagent_agent_names,
    subagent_question_for_child,
    subagents_from_profile,
)
from backend.realtime.helpers import (
    _resolve_agent_chat_params,
    agent_mcp_tool_ids,
    kb_search_agent_documents,
)
from backend.settings.logging import get_logger

log = get_logger(__name__)

# Ключ, под которым общий RAG цепочки протаскивается вниз по субагентам
# независимо от того, чей профиль сейчас является «родительским».
_SHARED_RAG_KEY = "_shared_chain_rag_ids"


def _parent_declares_subagent(
    parent_profile: Dict[str, Any], target_agent_id: int
) -> bool:
    """Субагент явно в карточке родителя (agent_ids) или self-spawn."""
    try:
        tid = int(target_agent_id)
    except (TypeError, ValueError):
        return False
    cfg = subagents_from_profile(parent_profile)
    if tid in cfg.agent_ids:
        return True
    if cfg.allow_self:
        parent_id = parent_profile.get("agent_id")
        try:
            if parent_id is not None and int(parent_id) == tid:
                return True
        except (TypeError, ValueError):
            pass
    return False


def _subagent_max_tokens_floor() -> int:
    """Пол max_tokens ребёнка - как у родителя в handlers (_run_ask).

    Длинные ответы (презентация, код) иначе рвутся на лимите карточки,
    :::artifact-блок остаётся незакрытым и до родителя не доезжает.
    """
    try:
        return max(int(os.getenv("SUBAGENT_MAX_TOKENS_FLOOR", "4096")), 256)
    except (TypeError, ValueError):
        return 4096


def _resolve_shared_chain_kb_ids(parent_profile: Dict[str, Any]) -> List[int]:
    """Список document_id общего RAG, если режим включён у головного агента.

    Значение сначала ищется в уже протянутом вниз ключе ``_SHARED_RAG_KEY``
    (чтобы наследоваться на всю глубину субагентов), затем — в самом профиле
    родителя (первый уровень субагентов от головного агента цепочки)."""
    if not isinstance(parent_profile, dict):
        return []
    inherited = parent_profile.get(_SHARED_RAG_KEY)
    if isinstance(inherited, list):
        return [
            int(v)
            for v in inherited
            if isinstance(v, (int, str)) and str(v).strip().lstrip("-").isdigit()
        ]
    if not parent_profile.get("shared_chain_rag"):
        return []
    if not parent_profile.get("file_search_enabled"):
        return []
    raw_ids = parent_profile.get("kb_document_ids") or []
    if not isinstance(raw_ids, list):
        return []
    out: List[int] = []
    for v in raw_ids:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


async def _build_shared_rag_context(
    prompt: str, kb_doc_ids: List[int]
) -> Tuple[str, Optional[Dict[str, Any]]]:
    """Найти релевантные фрагменты общей базы знаний под запрос субагента.

    Возвращает (текст для system prompt, document_search для UI) —
    у каждого субагента своя карточка источников.

    Субагент видит общую базу так же, как главный в своём чате:
    - фрагментов столько же - rag_chat_top_k главного (снимок настроек
      запроса - его), а не 8;
    - у каждого фрагмента имя файла - иначе ребёнок сочинял названия
      («Заключение_ДЭБ.docx (предполагаемое название)»);
    - в начале перечень ВСЕХ файлов базы: по 8 фрагментам из 7 файлов
      ребёнок решал, что остальных 20 в пакете нет («документов по БГ нет»).
    """
    if not kb_doc_ids:
        return "", None
    try:
        from backend.app_state import get_rag_chat_top_k, rag_client
        from backend.rag_query.context_budget import rag_context_max_chars
        from backend.realtime.rag_evidence import (
            build_rag_id_to_filename,
            build_rag_inventory_block,
            filter_rag_hits_by_score,
            format_rag_fragments,
            hits_to_document_search_trace,
            rag_guard_env,
            rag_scoped_filenames,
        )
    except Exception:
        log.exception("shared RAG: не удалось импортировать зависимости")
        return "", None
    if not rag_client:
        return "", None
    top_k = get_rag_chat_top_k("agent")
    try:
        hits: List[Tuple[str, float, Optional[int], Optional[int]]] = list(
            await kb_search_agent_documents(rag_client, prompt, kb_doc_ids, k=top_k) 
            or []
        )
    except Exception:
        log.exception("shared RAG: ошибка поиска по общей базе знаний")
        return "", None
    try:
        min_sim, _block = rag_guard_env("agent")
        hits = filter_rag_hits_by_score(hits, min_sim)
    except Exception:
        log.exception("shared RAG: фильтр по score")
    try:
        rows = list(await rag_client.kb_list_documents() or [])
        id_to_name = build_rag_id_to_filename(rows)
    except Exception:
        log.exception("shared RAG: список документов")
        id_to_name = {}
    # Перечень - только файлы общей базы главного, не вся KB: чужие имена
    # ребёнку показывать нельзя (см. rag_scoped_filenames).
    inventory = build_rag_inventory_block(
        [("Общая база знаний", rag_scoped_filenames(id_to_name, kb_doc_ids))]
    )    
    trace = hits_to_document_search_trace(
        query=prompt,
        hits=hits,
        id_to_name=id_to_name,
        store="shared_kb",
        strategy="auto",
    )
    parts: List[str] = []
    if hits:
        parts, _m = format_rag_fragments(
            hits,
            id_to_name,
            max_chars=rag_context_max_chars("kb (direct)"),
            store_label="kb (direct)",
            include_chunk_meta=False,
        )
    if not inventory and not parts:
        return "", trace
    body = "\n\n".join(p for p in (inventory, "".join(parts).strip()) if p)
    ctx = (
        "Используй приведённые ниже фрагменты из общей базы знаний цепочки агентов "
        "как контекст для ответа. Перечень файлов - полный список того, что "
        "загружено; фрагменты - найденное по задаче, у каждого указан файл. "
        "Если информации недостаточно — скажи об этом.\n\n"
        f"<shared_knowledge>\n{body}\n</shared_knowledge>"
    )
    return ctx, trace


async def _apply_child_kb_context(
    child_profile: Dict[str, Any],
    prompt: str,
    system_prompt: str,
    target_agent_id: int,
) -> Tuple[str, str, Optional[Dict[str, Any]]]:
    """База знаний ребёнка: тот же поиск и та же разметка, что в чате с ним.

    Раннер изолирует ребёнка от RAG родителя - это задумано (общий RAG
    цепочки - отдельный режим, см. shared_chain_rag) Но собственную
    базу ребёнка он тоже не читал: специалист по ВНД отвечал по памяти
    модели. Возвращает (prompt, system_prompt, document_search) - с фрагментами
    и правилами CONTEXT, либо нетронутые, если базы нет.

    Даже без релевантных hits в prompt кладётся перечень доступных файлов
    (как в обычном чате) — иначе вопрос «какие документы ты видишь?»
    оставался без ответа.
    """
    kb_ids = child_profile.get("kb_document_ids") or []
    if not (
        child_profile.get("file_search_enabled")
        and isinstance(kb_ids, list)
        and len(kb_ids) > 0
    ):
        log.info(
            "[chat-#tag/subagent] agent_id=%s: KB выключена или пуста "
            "(file_search=%s kb_ids=%s)",
            target_agent_id,
            bool(child_profile.get("file_search_enabled")),
            kb_ids,
        )
        return prompt, system_prompt, None
    # Документы, которые общий RAG цепочки (shared_chain_rag) уже положил в
    # системный промпт, второй раз не ищем: при вызове self это та же база.
    shared = {str(v) for v in (child_profile.get("_shared_chain_rag_ids") or [])}
    if shared:
        kb_ids = [i for i in kb_ids if str(i) not in shared]
        if not kb_ids:
            return prompt, system_prompt, None
    try:
        from backend.app_state import get_rag_chat_top_k, rag_client
        from backend.rag_query.context_budget import rag_context_max_chars
        from backend.rag_query.prompts import merge_strict_rag_system_prompt
        from backend.realtime.rag_evidence import (
            build_rag_id_to_filename,
            build_rag_inventory_block,
            filter_rag_hits_by_score,
            format_rag_fragments,
            hits_to_document_search_trace,
            rag_guard_env,
            rag_scoped_filenames,
        )

        if rag_client is None:
            log.warning(
                "[chat-#tag/subagent] agent_id=%s: rag_client недоступен, KB не подмешан",
                target_agent_id,
            )
            return prompt, system_prompt, None

        rows = list(await rag_client.kb_list_documents() or [])
        id_to_name = build_rag_id_to_filename(rows)
        inventory = build_rag_inventory_block(
            [
                (
                    "База Знаний агента",
                    rag_scoped_filenames(id_to_name, kb_ids),
                )
            ]
        )

        hits = list(
            await kb_search_agent_documents(
                rag_client,
                prompt,
                kb_ids,
                k=get_rag_chat_top_k("agent"),
                strategy="auto",
            )
            or []
        )
        min_sim, _block = rag_guard_env("agent")
        hits = filter_rag_hits_by_score(hits, min_sim)
        log.info(
            "[chat-#tag/subagent] agent_id=%s: KB docs=%s hits=%s inventory=%s",
            target_agent_id,
            len(kb_ids),
            len(hits),
            "да" if inventory else "нет",
        )

        trace = hits_to_document_search_trace(
            query=prompt,
            hits=hits,
            id_to_name=id_to_name,
            store="kb",
            strategy="auto",
        )

        prefix_parts: List[str] = []
        if inventory:
            prefix_parts.append(inventory)
        if hits:
            parts, _m = format_rag_fragments(
                hits,
                id_to_name,
                max_chars=rag_context_max_chars("kb (direct)"),
                store_label="kb (direct)",
                include_chunk_meta=False,
            )
            prefix_parts.append(
                f"База Знаний (постоянные документы):\n{''.join(parts)}"
            )

        if not prefix_parts:
            return prompt, system_prompt, trace

        new_prompt = "\n\n".join(prefix_parts) + f"\n\n{prompt}"
        # Промпт карточки - как rag_override: так же, как главному в его чате.
        # С rag_override=None правила RAG дописывались после карточки без
        # оговорки, чья инструкция главнее, и перебивали её формат ответа.
        new_system = merge_strict_rag_system_prompt(
            None, rag_override=system_prompt or None
        )
        return new_prompt, new_system, trace
    except Exception:
        # Переиндексация базы, недоступный SVC-RAG и т.п. - ребёнок отвечает
        # без документов; ронять родителя из-за него нельзя.
        log.exception(
            "[chat-#tag/subagent] agent_id=%s: поиск по базе не удался, отвечаю без неё",
            target_agent_id,
        )
        return prompt, system_prompt, None


async def _apply_child_skills_and_artifacts(
    child_profile: Dict[str, Any],
    prompt: str,
    system_prompt: str,
    user: Optional[dict],
    target_agent_id: int,
) -> Tuple[str, str, List[str]]:
    """Навыки и артефакты ребёнка - как в его собственном чате.

    Без этого ребёнок, который в своём чате рисует презентации и схемы,
    как субагент отвечал текстовым планом: инструкции про :::artifact у него
    не было, навыки карточки в промпт не попадали. Возвращает
    (prompt, system_prompt, доп. tool_ids из навыков).
    """
    extra_tools: List[str] = []
    lazy_ids: List[str] = []
    try:
        from backend.services.skills import apply_skills_to_chat, strip_skill_mentions

        new_system, _stripped, lazy_ids, extra_tools, _primed = await apply_skills_to_chat(
            system_prompt=system_prompt or None,
            user_message=prompt,
            data={},
            agent_profile=child_profile,
            current_user=user,
            history=None,
        )
        system_prompt = new_system or ""
        prompt = strip_skill_mentions(prompt)
        try:
            from backend.services.tag_mentions import strip_tag_mentions

            prompt = strip_tag_mentions(prompt)
        except Exception:
            pass
        if lazy_ids:
            # Отложенные навыки грузятся инструментом по __skill_ids__ из
            # контекста запроса. Контекст общий с родителем - дополняем, не
            # заменяем: у родителя от этого лишь больше разрешённых навыков.
            from backend.tools.tool_context import get_tool_context, set_tool_context

            ctx = dict(get_tool_context() or {})
            ctx["__skill_ids__"] = list(
                dict.fromkeys([*(ctx.get("__skill_ids__") or []), *lazy_ids])
            )
            if user is not None:
                ctx.setdefault("current_user", user)
            set_tool_context(ctx)
    except Exception:
        log.exception("subagent agent_id=%s: навыки не применились, иду без них", target_agent_id)
    artifacts_on = False
    try:
        from backend.prompts.artifacts import maybe_artifacts_prompt_for_agent
        from backend.services.skills import append_to_system_prompt

        block = maybe_artifacts_prompt_for_agent(child_profile)
        if block:
            system_prompt = append_to_system_prompt(system_prompt or None, block) or ""
            artifacts_on = True
    except Exception:
        log.exception("subagent agent_id=%s: артефакты не применились, иду без них", target_agent_id)
    log.debug(
        "subagent agent_id=%s: навыки отложенные=%s инструменты=%s артефакты=%s",
        target_agent_id,
        list(lazy_ids or []),
        list(extra_tools or []),
        "да" if artifacts_on else "нет",
    )
    return prompt, system_prompt, [str(t) for t in (extra_tools or []) if str(t).strip()]

async def _run_child_plugin(
    child_profile: Dict[str, Any],
    prompt: str,
    system_prompt: str,
    inline_attachments: Optional[List[Any]],
    target_agent_id: int,
    emit_event,
) -> Tuple[str, str, str]:
    """Плагин ребёнка на вложениях сообщения пользователя - как в его чате.

    Возвращает (prompt, system_prompt, artifact_markdown). Плагина нет -
    всё как было. Плагин есть, файла нет - в системный промпт подсказка.
    Файл есть - вердикт в промпт, подсказка в системный промпт, артефакт
    с полным вердиктом - в ответ ребёнка (его потом переносит 63).
    """
    try:
        from backend.plugins.orchestrator_bridge import resolve_agent_plugin_ids
        from backend.services.skills import append_to_system_prompt

        ids = resolve_agent_plugin_ids(child_profile)
    except Exception:
        log.exception("subagent agent_id=%s: не удалось прочитать плагины карточки", target_agent_id)
        return prompt, system_prompt, ""
    if not ids:
        return prompt, system_prompt, ""
    try:
        from backend.services.plugins_direct import (
            pick_plugin_run,
            prompt_block_for_outcome,
            run_plugin_direct,
            system_note_prerun,
        )

        run = pick_plugin_run(ids, inline_attachments, prompt, chat_mode="subagent")
        if not run:
            note = (
                "У тебя подключён плагин, но подходящего файла во вложениях сообщения "
                "пользователя нет - плагин не запускался. Отвечай по имеющимся данным и "
                "скажи, что для полного разбора нужен файл нужного формата, приложенный "
                "к сообщению."
            )
            return prompt, append_to_system_prompt(system_prompt or None, note) or "", ""

        import time
        import uuid

        from backend.agents.subagents import NATIVE_SERVER_ID
        from backend.mcp.events import emit_mcp_tool_end, emit_mcp_tool_start

        tool_name = f"plugin:{run.plugin_id}"
        call_id = uuid.uuid4().hex
        started = time.perf_counter()
        args = {"file": run.file_name, "agent_id": int(target_agent_id)}
        # Аудит идёт минуты - без карточки это выглядит как зависание.
        await emit_mcp_tool_start(
            emit_event,
            server_id=NATIVE_SERVER_ID,
            tool=tool_name,
            qualified_name=tool_name,
            call_id=call_id,
            arguments=args,
        )
        outcome = await run_plugin_direct(run, chat_mode="subagent")
        duration_ms = int((time.perf_counter() - started) * 1000)
        verdict = (outcome.verdict_markdown or "").strip()
        await emit_mcp_tool_end(
            emit_event,
            server_id=NATIVE_SERVER_ID,
            tool=tool_name,
            qualified_name=tool_name,
            success=bool(outcome.ok),
            duration_ms=duration_ms,
            error=None if outcome.ok else (outcome.error or "plugin failed"),
            result_preview=verdict[:500] if outcome.ok else None,
            call_id=call_id,
            arguments=args,
            result=verdict if outcome.ok else (outcome.error or ""),
        )
        log.info(
            "[subagent] плагин %s файл=«%s» успех=%s заняло=%s мс agent_id=%s",
            run.plugin_id,
            run.file_name,
            "да" if outcome.ok else "нет",
            duration_ms,
            target_agent_id,
        )
        new_prompt = f"{prompt_block_for_outcome(run, outcome)}\n\n{prompt}"
        new_system = append_to_system_prompt(system_prompt or None, system_note_prerun(run)) or ""
        return new_prompt, new_system, (outcome.artifact_markdown or "") if outcome.ok else ""
    except Exception:
        log.exception("subagent agent_id=%s: плагин не отработал, отвечаю без него", target_agent_id)
        return prompt, system_prompt, ""

def _with_child_plugin_artifact(text: str, artifact_markdown: str) -> str:
    """Дописать артефакт плагина к ответу ребёнка (если он есть)."""
    if not artifact_markdown:
        return text
    try:
        from backend.plugins.artifact_format import append_artifacts_to_answer

        return append_artifacts_to_answer(text, artifact_markdown)
    except Exception:
        log.exception("subagent: не удалось дописать артефакт плагина")
        return text


def _trace_files(trace: Optional[Dict[str, Any]]) -> Dict[str, int]:
    """Файл → сколько его фрагментов ушло ребёнку (по document_search)."""
    out: Dict[str, int] = {}
    for hit in (trace or {}).get("hits") or []:
        if isinstance(hit, dict) and hit.get("file"):
            out[str(hit["file"])] = out.get(str(hit["file"]), 0) + 1
    return out

def _log_subagent_trace(
    *,
    target_agent_id: int,
    child_profile: Dict[str, Any],
    parent_profile: Dict[str, Any],
    depth: int,
    task: str,
    question_added: bool,
    shared_kb_ids: List[int],
    shared_trace: Optional[Dict[str, Any]],
    child_kb_trace: Optional[Dict[str, Any]],
    system_prompt: str,
    prompt: str,
) -> None:
    """Одна строка [SUBAGENT-TRACE]: что субагент получил перед вызовом модели.

    Отвечает на вопросы «видит ли он свою карточку» и «какие документы он
    смотрел» без отладчика: промпт карточки на месте или нет, дошёл ли вопрос
    пользователя, по какой задаче искали, сколько фрагментов и из каких файлов пришло из общей базы главного
    и из своей. Только лог - в ответ и в UI ничего не уходит.
    """
    try:
        card = str(child_profile.get("system_prompt") or "").strip()
        # Навыки и артефакты дописывают в системный промпт, но карточку не
        # трогают: достаточно найти её начало.
        card_in = bool(card) and card[:200] in (system_prompt or "")
        try:
            from backend.app_state import get_rag_chat_top_k

            top_k = get_rag_chat_top_k("agent")
        except Exception:
            top_k = "?"
        shared_files = _trace_files(shared_trace)
        own_files = _trace_files(child_kb_trace)
        own_ids = child_profile.get("kb_document_ids") or []
        if shared_kb_ids:
            shared_part = (
                f"файлов в базе={len(shared_kb_ids)} top_k={top_k} "
                f"фрагментов={sum(shared_files.values())} "
                f"из {len(shared_files)} файлов {shared_files}"
            )
        else:
            shared_part = "нет (у главного не включён общий RAG)"
        if child_profile.get("file_search_enabled") and own_ids:
            own_part = (
                f"файлов={len(own_ids)} фрагментов={sum(own_files.values())} "
                f"из {len(own_files)} файлов {own_files}"
            )
        else:
            own_part = "нет (поиск по файлам выключен или файлов нет)"
        log.debug(
            "[SUBAGENT-TRACE] agent_id=%s «%s» родитель=%s глубина=%s модель=%s"
            " | карточка: %s симв, в системном промпте=%s"
            " | вопрос пользователя передан=%s"
            " | задача=«%s»"
            " | общий RAG: %s"
            " | своя база: %s"
            " | перечень файлов=%s"
            " | итог: системный=%s симв, сообщение=%s симв",
            target_agent_id,
            child_profile.get("name") or f"agent*{target_agent_id}",
            parent_profile.get("agent_id") if isinstance(parent_profile, dict) else None,
            depth,
            child_profile.get("model_path"),
            len(card),
            "да" if card_in else ("НЕТ" if card else "карточка пустая"),
            "да" if question_added else "нет",
            (task or "")[:300].replace("\n", " "),
            shared_part,
            own_part,
            "да" if "ДОСТУПНЫЕ ФАЙЛЫ" in f"{system_prompt}\n{prompt}" else "нет",
            len(system_prompt or ""),
            len(prompt or ""),
        )
    except Exception:
        log.exception("[SUBAGENT-TRACE] agent_id=%s: не удалось собрать", target_agent_id)


async def run_isolated_subagent(
    *,
    target_agent_id: int,
    prompt: str,
    parent_profile: Dict[str, Any],
    user: Optional[dict],
    user_id: Optional[str],
    depth: int,
    remaining_steps: int,
    history: Optional[List[Dict[str, Any]]] = None,
    enable_thinking: bool = False,
    emit_event=None,
    inline_attachments: Optional[List[Any]] = None,
    user_question: Optional[str] = None,
) -> SubagentOutcome:
    """Выполнить дочернего агента в изолированном контексте и вернуть итог."""
    # Если родитель объявил этого субагента в карточке — грузим профиль
    # без отдельного ACL на ребёнка (иначе шаринг/галерея родителя ломаются:
    # имя видно, а запуск пишет «not available»).
    trusted = _parent_declares_subagent(parent_profile, int(target_agent_id))
    child_profile = await _resolve_agent_chat_params(
        target_agent_id, user_id, user=user, skip_access_check=trusted
    )
    # agent_id проставляется только найденному агенту. Без него профиль пустой:
    # либо нет доступа (и родитель его не объявлял), либо агент удалён.
    if child_profile.get("agent_id") is None:
        log.warning(
            "subagent: agent_id=%s недоступен для user=%s trusted=%s",
            target_agent_id,
            user_id,
            trusted,
        )
        return SubagentOutcome(
            text=(
                f"Subagent {target_agent_id} is not available for this user "
                "(no access or deleted)."
            )
        )
    if not child_profile.get("model_path"):
        return SubagentOutcome(
            text=f"Subagent {target_agent_id}: model is not configured."
        )
    model_path = str(child_profile["model_path"])
    system_prompt = child_profile.get("system_prompt") or ""
    doc_traces: List[Optional[Dict[str, Any]]] = []
    # Вопрос пользователя дословно - рядом с заданием родителя. До поиска по
    # базам: искать тоже по обоим.
    task_with_question = subagent_question_for_child(user_question, prompt)
    question_added = task_with_question != prompt
    prompt = task_with_question
    task_text = prompt
    shared_trace: Optional[Dict[str, Any]] = None

    # Общий RAG цепочки/субагентов: если у головного агента включён общий RAG,
    # подмешиваем его базу знаний в контекст субагента и протаскиваем список
    # документов вниз по всей ветке дочерних субагентов.
    shared_kb_ids = _resolve_shared_chain_kb_ids(parent_profile)
    if shared_kb_ids:
        child_profile[_SHARED_RAG_KEY] = list(shared_kb_ids)
        shared_ctx, shared_trace = await _build_shared_rag_context(
            prompt, shared_kb_ids
        )
        if shared_trace:
            doc_traces.append(shared_trace)
        if shared_ctx:
            system_prompt = (
                f"{system_prompt}\n\n{shared_ctx}" if system_prompt else shared_ctx
            )
            log.info(
                "[subagent] общий RAG цепочки: agent_id=%s документов=%s hits=%s",
                target_agent_id,
                len(shared_kb_ids),
                len((shared_trace or {}).get("hits") or []),
            )

    prompt, system_prompt, child_kb_trace = await _apply_child_kb_context(
        child_profile, prompt, system_prompt, int(target_agent_id)
    )
    if child_kb_trace:
        doc_traces.append(child_kb_trace)

    from backend.realtime.rag_evidence import merge_document_search_traces

    document_search = merge_document_search_traces(*doc_traces)

    sub_cfg = subagents_from_profile(child_profile)
    child_limit = min(remaining_steps, resolve_recursion_limit(child_profile))
    child_limit = max(1, child_limit)
    log_pre_loop(
        phase="subagent_start",
        agent_id=target_agent_id,
        recursion_limit=child_limit,
        limit_source=(
            f"мин(осталось шагов={remaining_steps}, {describe_limit_source(child_profile)})"
        ),
        detail=(
            f"родитель={parent_profile.get('agent_id')} глубина={depth} "
            f"модель={model_path} запрос=«{prompt[:120]}»"
        ),
    )

    prompt, system_prompt, _skill_tool_ids = await _apply_child_skills_and_artifacts(
        child_profile, prompt, system_prompt, user, int(target_agent_id)
    )
    # Инструменты навыков - в цикл ребёнка, как у родителя в _handle_direct.
    tool_ids = list(dict.fromkeys([*agent_mcp_tool_ids(child_profile), *_skill_tool_ids]))
    # Лимит карточки снизу поднимаем до пола - как родителю в своём чате.
    card_max_tokens = int(child_profile.get("max_tokens") or 1024)
    child_max_tokens = max(card_max_tokens, _subagent_max_tokens_floor())
    log.debug(
        "[subagent] agent_id=%s max_tokens: карточка=%s → эффективно=%s thinking=%s",
        target_agent_id,
        card_max_tokens,
        child_max_tokens,
        enable_thinking,
    )
    prompt, system_prompt, child_plugin_artifact = await _run_child_plugin(
        child_profile, prompt, system_prompt, inline_attachments, int(target_agent_id), emit_event
    )
    names = await load_subagent_agent_names(
        sub_cfg.agent_ids,
        user_id=user_id,
        snapshot_names=sub_cfg.agent_names,
    )
    if child_profile.get("name"):
        names[int(target_agent_id)] = str(child_profile["name"])
    native_tools = build_subagent_tools(
        sub_cfg,
        parent_agent_id=child_profile.get("agent_id"),
        agent_names=names,
    )

    messages: List[Dict[str, Any]] = []
    if system_prompt:
        messages.append({"role": "system", "content": system_prompt})
    if history:
        for item in history[-6:]:
            role = str(item.get("role") or "user")
            content = str(item.get("content") or "")
            if content:
                messages.append({"role": role, "content": content})
    # История ребёнка: то, что уже собрано выше из history[-6:], без
    # системного. Раньше messages никуда не уходили - история терялась.
    child_history: List[Dict[str, Any]] = [
        m for m in messages if m.get("role") in ("user", "assistant")
    ]
    messages.append({"role": "user", "content": prompt})
    _log_subagent_trace(
        target_agent_id=int(target_agent_id),
        child_profile=child_profile,
        parent_profile=parent_profile,
        depth=depth,
        task=task_text,
        question_added=question_added,
        shared_kb_ids=shared_kb_ids,
        shared_trace=shared_trace,
        child_kb_trace=child_kb_trace,
        system_prompt=system_prompt,
        prompt=prompt,
    )

    def _finish(text: str) -> SubagentOutcome:
        return SubagentOutcome(
            text=_with_child_plugin_artifact(text, child_plugin_artifact),
            document_search=document_search,
        )

    if tool_ids or native_tools:
        from backend.mcp.chat_integration import maybe_run_mcp_agent
        from backend.mcp.chat_integration import build_mcp_context_from_user

        mcp_ctx = build_mcp_context_from_user(user or {}, chat_id=None, message_id=None)

        async def _child_executor(**kwargs):
            return await run_isolated_subagent(
                target_agent_id=kwargs["target_agent_id"],
                prompt=kwargs["prompt"],
                parent_profile=kwargs["parent_profile"],
                user=kwargs.get("user"),
                user_id=kwargs.get("user_id"),
                depth=kwargs.get("depth", depth),
                remaining_steps=kwargs.get("remaining_steps", child_limit - 1),
                enable_thinking=enable_thinking,
                emit_event=emit_event,
                inline_attachments=kwargs.get("inline_attachments", inline_attachments),
                user_question=kwargs.get("user_question", user_question),
            )

        subagent_ctx = SubagentRunContext(
            parent_agent_id=child_profile.get("agent_id"),
            parent_profile=child_profile,
            user=user,
            user_id=user_id,
            depth=depth,
            remaining_steps=child_limit - 1,
            executor=_child_executor,
            inline_attachments=inline_attachments,
            agent_names=dict(names),
            user_question=user_question,
        )
        result = await maybe_run_mcp_agent(
            tool_ids=tool_ids or None,
            user_message=prompt,
            history=child_history,
            system_prompt=system_prompt or None,
            model_path=model_path,
            mcp_context=mcp_ctx,
            temperature=float(child_profile.get("temperature") or 0.7),
            max_tokens=child_max_tokens,
            enable_thinking=enable_thinking,
            event_callback=emit_event,
            max_iterations=child_limit,
            native_tools=native_tools,
            subagent_ctx=subagent_ctx,
            subagent_config=sub_cfg,
        )
        if result is not None:
            if result.content:
                return _finish(result.content.strip())
            return _finish("Subagent finished without a response.")
        # None - цикл инструментов не запускался вовсе: MCP-сервер ребёнка
        # выключен или недоступен, нативных инструментов нет. Раньше здесь
        # отвечали «finished without a response», хотя модель ребёнка даже
        # не вызывалась. Проваливаемся в обычный вызов ниже.
        log.warning(
            "subagent agent_id=%s: инструменты недоступны (tool_ids=%s), отвечаю без них",
            target_agent_id,
            tool_ids,
        )

    from backend.app_state import ask_agent

    _ctx = contextvars.copy_context()
    _call = functools.partial(
        ask_agent,
        prompt,
        history=child_history,
        max_tokens=child_max_tokens,
        streaming=True,
        stream_callback=None,
        model_path=model_path,
        custom_prompt_id=None,
        images=None,
        system_prompt=system_prompt or None,
        temperature=child_profile.get("temperature"),
        enable_thinking=enable_thinking,
    )
    response = await asyncio.get_running_loop().run_in_executor(
        None, functools.partial(_ctx.run, _call)
    )
    return _finish(
        str(response or "").strip() or "Subagent finished without a response."
    )
