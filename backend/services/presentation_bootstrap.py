"""Opt-in, first-run provisioning for the Inter RAO presentation deployment."""

import json
import os
from pathlib import Path

from backend.settings.logging import get_logger

logger = get_logger(__name__)
BOOTSTRAP_KEY = "inter-rao-presentation-v2"
SKILL_SLUG = "presentation-inter-rao-v2"


async def bootstrap_presentation_agent(db_connection) -> None:
    skill_path = os.getenv("PRESENTATION_BOOTSTRAP_SKILL_PATH", "").strip()
    if not skill_path:
        return

    content = Path(skill_path).read_text(encoding="utf-8")
    if not content.strip():
        raise ValueError("Presentation bootstrap skill is empty")
    owner = os.getenv("PRESENTATION_AGENT_OWNER", "admin").strip().lower()
    config = {
        "model_path": os.getenv(
            "PRESENTATION_MODEL_PATH", "openrouter/@preset/astra-studio-chat"
        ),
        "model_settings": {"output_tokens": 32768},
        "skills_enabled": True,
        "skill_ids": [SKILL_SLUG],
        "artifacts_enabled": True,
        # The supplied skill defines HTML/CSS slides; the generic artifact prompt
        # would require Mermaid charts and a different output wrapper.
        "user_prompt_mode": True,
        "shadcn_enabled": False,
        "mcp_enabled": False,
        "plugins_enabled": False,
        "kb_document_ids": [],
        "agent_ids": [],
        "shared_chain_rag": False,
    }
    async with await db_connection.acquire() as conn:
        async with conn.transaction():
            # Serialize concurrent startup workers; both records commit together.
            await conn.execute("SELECT pg_advisory_xact_lock($1)", 2026100301)
            await conn.execute(
                """
                CREATE TABLE IF NOT EXISTS deployment_defaults (
                    deployment_key TEXT PRIMARY KEY,
                    agent_id INTEGER REFERENCES agents(id) ON DELETE SET NULL,
                    skill_id INTEGER REFERENCES skills(id) ON DELETE SET NULL
                )
                """
            )
            defaults = await conn.fetchrow(
                "SELECT agent_id, skill_id FROM deployment_defaults WHERE deployment_key = $1",
                BOOTSTRAP_KEY,
            )
            agent_id = defaults["agent_id"] if defaults else None
            skill_id = defaults["skill_id"] if defaults else None
            # Store IDs separately from editable agent config and skill slugs.
            if skill_id is None:
                await conn.execute(
                    """
                    INSERT INTO skills (
                        slug, name, display_title, description, content, meta,
                        is_active, is_public, always_apply, version, author_id, author_name
                    ) VALUES ($1, $2, $2, $3, $4, $5::jsonb, true, true, true, 2, $6, $6)
                    ON CONFLICT (slug) DO NOTHING
                    """,
                    SKILL_SLUG,
                    "Презентации Интер РАО — шаблон v2",
                    "HTML-презентации в корпоративном стиле Интер РАО с экспортом в PPTX.",
                    content,
                    json.dumps({"bootstrap_key": BOOTSTRAP_KEY}),
                    owner,
                )
                existing = await conn.fetchrow(
                    "SELECT id, meta->>'bootstrap_key' AS bootstrap_key FROM skills WHERE slug = $1",
                    SKILL_SLUG,
                )
                if existing["bootstrap_key"] != BOOTSTRAP_KEY:
                    raise ValueError("Presentation skill slug is already used by another skill")
                skill_id = existing["id"]
            if agent_id is None:
                config["skill_ids"] = [await conn.fetchval(
                    "SELECT slug FROM skills WHERE id = $1", skill_id
                )]
                agent_id = await conn.fetchval(
                    """
                    INSERT INTO agents (
                        name, description, system_prompt, config, tools,
                        author_id, author_name, is_public
                    ) VALUES ($1, $2, $3, $4::jsonb, '[]'::jsonb, $5, $5, true)
                    RETURNING id
                    """,
                    "Презентации RAO",
                    "Презентации Интер РАО: шаблон v2, превью и скачивание PPTX.",
                    "Ты помогаешь готовить презентации Интер РАО. Следуй приложенному "
                    "скиллу шаблона v2. Создавай полную HTML-презентацию с локальными "
                    "иконками. Пользователь скачивает PPTX из превью. Не выдумывай факты "
                    "и числовые данные; при необходимости уточни их у пользователя.",
                    json.dumps(config, ensure_ascii=False),
                    owner,
                )
            await conn.execute(
                """
                INSERT INTO deployment_defaults (deployment_key, agent_id, skill_id)
                VALUES ($1, $2, $3)
                ON CONFLICT (deployment_key) DO UPDATE
                SET agent_id = EXCLUDED.agent_id, skill_id = EXCLUDED.skill_id
                """,
                BOOTSTRAP_KEY, agent_id, skill_id,
            )
    # Existing records remain editable: a restart does not overwrite UI changes.
    logger.info("Presentation bootstrap ready: agent_id=%s, skill=%s", agent_id, SKILL_SLUG)
