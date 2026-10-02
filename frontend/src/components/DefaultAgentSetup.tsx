import React, { useEffect, useState } from 'react';
import { Box, Button, CircularProgress, Typography } from '@mui/material';
import { useAuth } from '../contexts/AuthContext';
import { getApiUrl } from '../config/api';
import { persistAgentArtifactsEnabled } from '../utils/agentArtifactsEnabled';
import { persistAgentMcpConfig } from '../utils/applyAgentMcp';
import { rememberAgentModelPath } from '../utils/applyAgentServer';

const defaultAgentKey = process.env.REACT_APP_DEFAULT_AGENT_KEY || '';
const activeAgentOwnerKey = 'astra_active_agent_owner';

/** Initialize before mounting the chat so its first message includes the agent. */
export default function DefaultAgentSetup({ children }: { children: React.ReactElement }) {
  const { token, user } = useAuth();
  const userId = user?.user_id || user?.username || '';
  const [readyFor, setReadyFor] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (!defaultAgentKey || !token || !userId) return;
    const marker = `astra_default_agent:${defaultAgentKey}:${userId}`;
    // Choosing another agent (including no agent) remains a user decision.
    if (localStorage.getItem(marker) === '1' && localStorage.getItem(activeAgentOwnerKey) === userId) {
      setReadyFor(userId);
      return;
    }
    let cancelled = false;
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 15000);
    setFailed(false);
    const initialize = async () => {
      try {
        const response = await fetch(getApiUrl('/api/agents/default'), {
          headers: { Authorization: `Bearer ${token}` },
          signal: controller.signal,
        });
        if (!response.ok) throw new Error('Default agent unavailable');
        const { agent } = await response.json();
        if (!agent?.id || !agent?.name) throw new Error('Default agent missing');
        if (cancelled) return;
        const config = (agent.config || {}) as Record<string, unknown>;
        localStorage.setItem('active_agent_id', String(agent.id));
        localStorage.setItem('active_agent_name', agent.name);
        localStorage.setItem('active_agent_prompt', agent.system_prompt || '');
        persistAgentMcpConfig(config);
        persistAgentArtifactsEnabled(config);
        rememberAgentModelPath(String(config.model_path || config.model || ''));
        localStorage.setItem(marker, '1');
        localStorage.setItem(activeAgentOwnerKey, userId);
        window.dispatchEvent(new CustomEvent('agentSelected', { detail: agent }));
        setReadyFor(userId);
      } catch {
        if (!cancelled) setFailed(true);
      } finally {
        window.clearTimeout(timeout);
      }
    };
    void initialize();
    return () => {
      cancelled = true;
      controller.abort();
      window.clearTimeout(timeout);
    };
  }, [token, userId, attempt]);

  if (!defaultAgentKey || readyFor === userId) return children;
  return (
    <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'center', minHeight: '100vh', gap: 2 }}>
      {failed ? (
        <>
          <Typography>Не удалось подготовить чат.</Typography>
          <Button onClick={() => setAttempt((value) => value + 1)}>Повторить</Button>
        </>
      ) : <CircularProgress />}
    </Box>
  );
}
