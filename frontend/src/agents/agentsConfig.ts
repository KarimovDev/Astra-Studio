/** Лимиты цепочки агентов, субагентов и шагов агента (GET /api/agents/chain-config). */
import { getApiUrl, getAuthFetchHeaders } from '../config/api';

/** Дефолт, если ConfigMap ещё не подтянулся. */
export const DEFAULT_MAX_CHAIN_AGENTS = 10;
export const DEFAULT_MAX_SUBAGENTS = 10;
export const DEFAULT_GRAPH_STEPS = 50;

export interface AgentChainConfig {
  maxAgents: number;
  maxAgentsCap: number;
  maxSubagents: number;
  maxSubagentsCap: number;
  graphSteps: number;
  defaultRecursionLimit: number;
  maxRecursionLimit: number;
}

let cachedConfig: AgentChainConfig | null = null;
let loadPromise: Promise<AgentChainConfig> | null = null;

function clampLimit(raw: unknown, fallback: number, lo: number, hi: number): number {
  const n = Number(raw);
  if (!Number.isFinite(n)) return fallback;
  return Math.max(lo, Math.min(Math.trunc(n), hi));
}

export function getCachedChainConfig(): AgentChainConfig {
  return (
    cachedConfig || {
      maxAgents: DEFAULT_MAX_CHAIN_AGENTS,
      maxAgentsCap: 50,
      maxSubagents: DEFAULT_MAX_SUBAGENTS,
      maxSubagentsCap: 50,
      graphSteps: DEFAULT_GRAPH_STEPS,
      defaultRecursionLimit: DEFAULT_GRAPH_STEPS,
      maxRecursionLimit: 500,
    }
  );
}

export async function fetchAgentChainConfig(): Promise<AgentChainConfig> {
  if (cachedConfig) return cachedConfig;
  if (!loadPromise) {
    loadPromise = (async () => {
      try {
        const resp = await fetch(getApiUrl('/api/agents/chain-config'), {
          headers: getAuthFetchHeaders(),
        });
        const data = resp.ok ? await resp.json() : {};
        cachedConfig = {
          maxAgents: clampLimit(data.max_agents ?? data.maxAgents, DEFAULT_MAX_CHAIN_AGENTS, 1, 50),
          maxAgentsCap: clampLimit(data.max_agents_cap ?? data.maxAgentsCap, 50, 1, 50),
          maxSubagents: clampLimit(
            data.max_subagents ?? data.maxSubagents,
            DEFAULT_MAX_SUBAGENTS,
            1,
            50,
          ),
          maxSubagentsCap: clampLimit(data.max_subagents_cap ?? data.maxSubagentsCap, 50, 1, 50),
          graphSteps: clampLimit(data.graph_steps ?? data.graphSteps, DEFAULT_GRAPH_STEPS, 1, 500),
          defaultRecursionLimit: clampLimit(
            data.default_recursion_limit ?? data.graph_steps ?? data.graphSteps,
            DEFAULT_GRAPH_STEPS,
            1,
            500,
          ),
          maxRecursionLimit: clampLimit(
            data.max_recursion_limit ?? data.maxRecursionLimit,
            500,
            1,
            500,
          ),
        };
        return cachedConfig;
      } catch {
        cachedConfig = {
          maxAgents: DEFAULT_MAX_CHAIN_AGENTS,
          maxAgentsCap: 50,
          maxSubagents: DEFAULT_MAX_SUBAGENTS,
          maxSubagentsCap: 50,
          graphSteps: DEFAULT_GRAPH_STEPS,
          defaultRecursionLimit: DEFAULT_GRAPH_STEPS,
          maxRecursionLimit: 500,
        };
        return cachedConfig;
      }
    })();
  }
  return loadPromise;
}

export function parseAgentIds(
  raw: unknown,
  excludeId?: number | null,
  maxAgents: number = getCachedChainConfig().maxAgents,
): number[] {
  if (!Array.isArray(raw)) return [];
  const seen = new Set<number>();
  if (typeof excludeId === 'number' && Number.isFinite(excludeId)) seen.add(excludeId);
  const limit = Math.max(1, maxAgents);
  const out: number[] = [];
  for (const item of raw) {
    const id = Number(item);
    if (!Number.isFinite(id) || id <= 0 || seen.has(id)) continue;
    seen.add(id);
    out.push(id);
    if (out.length >= limit) break;
  }
  return out;
}

/** @deprecated используйте getCachedChainConfig().maxAgents */
export const MAX_CHAIN_AGENTS = DEFAULT_MAX_CHAIN_AGENTS;
