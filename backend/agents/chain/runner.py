
"""Запуск цепочки агентов в чате: шаг за шагом, итог - одним ответом.

Был в realtime/handlers.py (_run_direct_or_chain). Каждый шаг - обычный
_handle_direct handlers со своим профилем; здесь - порядок шагов, что шаг
получает от предыдущих и общий RAG головного агента.
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional

from backend.agents.chain.profiles import prepare_step_socket_data, resolve_agent_chain
from backend.agents.chain.prompts import (
    build_chain_user_message,
    format_visible_chain_content,
    iter_chain_stream_prefixes,
)
from backend.agents.config import resolve_recursion_limit
from backend.agents.shared_rag import accepts_parent_shared_rag, head_shared_kb_ids
from backend.agents.step_debug import log_chain_hop
from backend.settings.logging import get_logger

log = get_logger(__name__)


async def run_direct_or_chain(
    sio,
    sid,
    data,
    user_message,
    streaming,
    conversation_id,
    history,
    use_kb_rag,
    use_memory_library_rag,
    agent_profile,
    sync_stream_cb,
    loop,
    use_agent_scoped_kb=False,
    agent_kb_doc_ids=None,
    project_id=None,
    project_instructions=None,
    rag_strategy="auto",
    current_user=None,
    enable_thinking=False,
    inline_context: str = "",
    inline_images: list = None,
    generation_started_at: Optional[float] = None,
):
    """Один агент или последовательная цепочка Mixture-of-Agents.

    Один агент - обычный _handle_direct. Цепочка - _handle_direct на каждый
    шаг, итог одним ответом. Сокет, стрим и сохранение - хелперы handlers.
    """
    from backend.realtime import handlers as rt

    user_id = (
        (current_user or {}).get("user_id") if isinstance(current_user, dict) else None
    )
    chain = await resolve_agent_chain(
        data.get("agent_id") if isinstance(data, dict) else None,
        agent_profile,
        user_id,
        user=current_user if isinstance(current_user, dict) else None,
    )
    if len(chain) <= 1:
        await rt._handle_direct(
            sio,
            sid,
            data,
            user_message,
            streaming,
            conversation_id,
            history,
            use_kb_rag,
            use_memory_library_rag,
            agent_profile,
            sync_stream_cb,
            loop,
            use_agent_scoped_kb,
            agent_kb_doc_ids,
            project_id=project_id,
            project_instructions=project_instructions,
            rag_strategy=rag_strategy,
            current_user=current_user,
            enable_thinking=enable_thinking,
            inline_context=inline_context,
            inline_images=inline_images,
            generation_started_at=generation_started_at,
        )
        return

    hide_seq = bool((chain[0] or {}).get("hide_sequential_outputs"))
    # Общий RAG для цепочки: головной агент (chain[0]) делится своей базой знаний
    # со всеми последующими агентами. Индивидуальный per-agent RAG при этом не трогаем —
    # он продолжает работать для одиночных агентов и когда флаг выключен.
    shared_kb_ids = head_shared_kb_ids(chain[0] or {})
    steps: list = []
    # #теги: фиксируем id в payload первого шага и убираем mentions из текста,
    # чтобы следующие hop и история не тащили сырой <#id|…>.
    if isinstance(data, dict):
        try:
            from backend.services.tag_mentions import (
                collect_mention_tag_ids,
                strip_tag_mentions,
            )

            mention_tags = collect_mention_tag_ids(
                user_message=user_message, data=data
            )
            if mention_tags:
                data = dict(data)
                data["tag_ids"] = mention_tags
            original_message = strip_tag_mentions(user_message)
        except Exception:
            original_message = user_message
    else:
        original_message = user_message
    log.info(
        "[шаги агента] Старт цепочки: %s агентов подряд | скрывать промежуточные=%s | "
        "id=%s | чат=%s (это смена агентов, не лимит шагов LLM↔инструменты)",
        len(chain),
        hide_seq,
        [p.get("agent_id") for p in chain],
        conversation_id,
    )
    log.debug(
        "[agent-chain] start n=%s hide_sequential=%s ids=%s",
        len(chain),
        hide_seq,
        [p.get("agent_id") for p in chain],
    )

    for i, profile in enumerate(chain):
        if rt._generation_stopped(sid):
            await sio.emit(
                "generation_stopped",
                rt._stream_ids_payload({"message": "Генерация остановлена"}),
                room=sid,
            )
            return
        is_first = i == 0
        is_last = i == len(chain) - 1
        step_name = (profile.get("name") or "Агент").strip() or "Агент"
        step_kb_ids_peek = profile.get("kb_document_ids") or []
        step_use_kb_peek = (
            bool(profile.get("file_search_enabled"))
            and isinstance(step_kb_ids_peek, list)
            and len(step_kb_ids_peek) > 0
        )
        log_chain_hop(
            index=i + 1,
            total=len(chain),
            agent_id=profile.get("agent_id"),
            agent_name=step_name,
            chat_id=conversation_id,
            has_rag=bool(
                (use_kb_rag if is_first else False)
                or use_memory_library_rag
                or step_use_kb_peek
                or project_id
            ),
            recursion_limit=resolve_recursion_limit(
                profile if isinstance(profile, dict) else None
            ),
        )
        await sio.emit(
            "chat_agent_update",
            rt._stream_ids_payload(
                {
                    "agent_id": profile.get("agent_id"),
                    "agent_name": step_name,
                    "index": i,
                    "total": len(chain),
                    "hide_sequential": hide_seq,
                    "is_last": is_last,
                }
            ),
            room=sid,
        )
        if hide_seq and not is_last:
            await sio.emit(
                "chat_thinking",
                rt._stream_ids_payload(
                    {
                        "status": "processing",
                        "message": f"{step_name} думает…",
                        "agent_chain": True,
                    }
                ),
                room=sid,
            )

        step_profile = await rt.enrich_agent_profile_with_user_settings(profile, user_id)
        _eff_ms = (
            step_profile.get("effective_model_settings")
            if isinstance(step_profile, dict)
            else None
        )
        if isinstance(_eff_ms, dict) and _eff_ms:
            rt.bind_user_model_runtime(_eff_ms)

        # Шаг, у которого в карточке выключено «Смотреть общий RAG родителя»,
        # ищет по своей базе - как без общего RAG. Головной (первый шаг) -
        # всегда по своей: она и есть общая.
        step_takes_shared = bool(shared_kb_ids) and (
            is_first or accepts_parent_shared_rag(step_profile)
        )
        if shared_kb_ids and not step_takes_shared:
            log.info(
                "[agent-chain] шаг %s/%s agent_id=%s: в карточке выключено «Смотреть "
                "общий RAG родителя» - ищет по своей базе",
                i + 1,
                len(chain),
                profile.get("agent_id"),
            )
        if step_takes_shared:
            # Общая база знаний головного агента для каждого шага цепочки.
            step_kb_ids = list(shared_kb_ids)
            step_use_kb = True
        else:
            step_kb_ids = step_profile.get("kb_document_ids") or []
            step_use_kb = (
                bool(step_profile.get("file_search_enabled"))
                and isinstance(step_kb_ids, list)
                and len(step_kb_ids) > 0
            )
        step_data = prepare_step_socket_data(data, step_profile, is_first=is_first)
        step_message = (
            original_message
            if is_first
            else build_chain_user_message(original_message, steps)
        )
        stream_prefix, _header = iter_chain_stream_prefixes(
            steps, step_name, hide_sequential_outputs=hide_seq
        )
        step_profile["_chain_trace"] = {
            "index": i + 1,
            "total": len(chain),
            "prev": [
                {
                    "agent_id": p.get("agent_id"),
                    "system_prompt": str(p.get("system_prompt") or ""),
                    "output": str(s.get("content") or ""),
                }
                for p, s in zip(chain[:i], steps)
            ],
        }

        raw = await rt._handle_direct(
            sio,
            sid,
            step_data,
            step_message,
            streaming,
            conversation_id,
            history,
            use_kb_rag if is_first else False,
            use_memory_library_rag,
            step_profile,
            sync_stream_cb,
            loop,
            step_use_kb,
            step_kb_ids,
            project_id=project_id,
            project_instructions=project_instructions,
            rag_strategy=rag_strategy,
            current_user=current_user,
            enable_thinking=enable_thinking,
            inline_context=inline_context if is_first else "",
            inline_images=inline_images if is_first else None,
            generation_started_at=generation_started_at,
            rag_query=original_message,
            stream_prefix=stream_prefix,
            emit_complete=False,
            save_response=False,
            suppress_ui_stream=hide_seq and not is_last,
        )
        if raw is None or rt._generation_stopped(sid):
            return
        step_content = raw.get("content") if isinstance(raw, dict) else raw
        step_reasoning = raw.get("reasoning") if isinstance(raw, dict) else ""
        step_document_search = (
            raw.get("document_search") if isinstance(raw, dict) else None
        )
        steps.append(
            {
                "agent_id": profile.get("agent_id"),
                "agent_name": step_name,
                "content": step_content or "",
                "reasoning": step_reasoning or "",
                "document_search": step_document_search or None,
            }
        )

    visible = format_visible_chain_content(steps, hide_sequential_outputs=hide_seq)
    last_profile = chain[-1]
    last_name = (last_profile.get("name") or "Агент").strip() or "Агент"
    await rt._flush_ui_stream_cb(sync_stream_cb)
    payload = rt._stream_ids_payload(
        {
            "response": visible,
            "timestamp": datetime.now().isoformat(),
            "was_streaming": streaming,
            "generation_duration_sec": rt._generation_duration_sec(generation_started_at),
            "chain_steps": steps,
            "hide_sequential_outputs": hide_seq,
            "agent_id": last_profile.get("agent_id"),
            "agent_name": last_name,
        }
    )
    await sio.emit("chat_complete", payload, room=sid)
    try:
        meta = {
            "chain_steps": steps,
            "hide_sequential_outputs": hide_seq,
        }
        meta = rt._with_generation_duration(meta, generation_started_at)
        regen = rt._regen_save_kwargs(data)
        await rt.save_assistant_response(
            visible,
            meta,
            conversation_id=conversation_id,
            user_id=user_id,
            project_id=project_id,
            **regen,
        )
    except Exception as e:
        log.warning(f"Не удалось сохранить ответ цепочки: {e}")
