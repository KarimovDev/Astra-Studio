
"""Субагенты: изолированные дочерние запуски через tool `subagent`.

  settings.py      - config.subagents карточки, лимиты, выбор ребёнка
  names.py         - имена субагентов для модели и для карточек в чате
  tool.py          - инструмент subagent: описание, запуск по вызову
  answers.py       - метки [[ОТВЕТ N]], правила родителю, задание ребёнку
  parent.py        - субагенты в цикле инструментов родителя
  runner.py        - запуск ребёнка (run_isolated_subagent)
  child_context.py - что ребёнок получает: базы знаний, навыки, плагин
  scope.py         - в каких файлах ищет ребёнок («смотри только …»)
  trace.py         - лог [SUBAGENT-TRACE]
  required.py      - обязательные субагенты по тегам и #теги в чате
  artifacts.py     - артефакты детей в ответ родителя

Общий RAG головного агента - backend/agents/shared_rag.py (он же у цепочки).
Здесь - лёгкая часть (без раннера), как раньше в agents/subagents.py:
`from backend.agents.subagents import X` работает для прежних имён.
"""

from backend.agents.subagents.answers import (
    SUBAGENT_ANSWER_MARK,
    SUBAGENT_RULES,
    append_subagent_rules,
    expand_subagent_answers,
    subagent_question_for_child,
    subagent_result_for_model,
)
from backend.agents.subagents.names import (
    enrich_agents_subagent_names,
    load_subagent_agent_names,
    resolve_subagent_display_name,
    short_agent_label,
    with_subagent_display_name,
)
from backend.agents.subagents.settings import (
    MAX_SUBAGENT_DEPTH,
    MAX_SUBAGENTS,
    MAX_SUBAGENTS_CAP,
    NATIVE_SERVER_ID,
    SELF_SUBAGENT_TYPE,
    SUBAGENT_TOOL_NAME,
    AgentSubagentsConfig,
    get_max_subagents,
    parse_agent_names_map,
    parse_subagents_config,
    profile_recursion_limit,
    resolve_max_subagents,
    resolve_subagent_target,
    subagent_type_for_agent_id,
    subagents_from_profile,
)
from backend.agents.subagents.tool import (
    SubagentExecutor,
    SubagentOutcome,
    SubagentRunContext,
    build_subagent_tools,
    execute_native_tool,
    execute_subagent_tool,
)

__all__ = [
    "MAX_SUBAGENT_DEPTH",
    "MAX_SUBAGENTS",
    "MAX_SUBAGENTS_CAP",
    "NATIVE_SERVER_ID",
    "SELF_SUBAGENT_TYPE",
    "SUBAGENT_ANSWER_MARK",
    "SUBAGENT_RULES",
    "SUBAGENT_TOOL_NAME",
    "AgentSubagentsConfig",
    "SubagentExecutor",
    "SubagentOutcome",
    "SubagentRunContext",
    "append_subagent_rules",
    "build_subagent_tools",
    "enrich_agents_subagent_names",
    "execute_native_tool",
    "execute_subagent_tool",
    "expand_subagent_answers",
    "get_max_subagents",
    "load_subagent_agent_names",
    "parse_agent_names_map",
    "parse_subagents_config",
    "profile_recursion_limit",
    "resolve_max_subagents",
    "resolve_subagent_display_name",
    "resolve_subagent_target",
    "short_agent_label",
    "subagent_question_for_child",
    "subagent_result_for_model",
    "subagent_type_for_agent_id",
    "subagents_from_profile",
    "with_subagent_display_name",
]
