import React from 'react';
import { Box, Chip, CircularProgress } from '@mui/material';
import AgentIcon from '../../icons/AgentIcon';
import HubIcon from '../../icons/McpIcon';
import type { McpToolCallRecord } from '../types';

interface McpLiveToolsIndicatorProps {
  tools: McpToolCallRecord[];
}

/** Live-индикатор вызова tools (субагенты / native / MCP) во время генерации. */
export default function McpLiveToolsIndicator({ tools }: McpLiveToolsIndicatorProps) {
  if (!tools.length) return null;

  const hasSubagent = tools.some((t) => t.tool === 'subagent');
  const Icon = hasSubagent ? AgentIcon : HubIcon;

  return (
    <Box sx={{ display: 'flex', alignItems: 'center', flexWrap: 'wrap', gap: 0.75, mb: 1, px: 0.5 }}>
      <CircularProgress size={14} sx={{ flexShrink: 0 }} />
      <Icon sx={{ fontSize: 16, color: 'primary.main' }} />
      {tools.map((t) => {
        const agentName =
          t.tool === 'subagent' &&
          t.arguments &&
          typeof t.arguments.agent_name === 'string'
            ? t.arguments.agent_name.trim()
            : '';
        const base = agentName || t.tool;
        return (
          <Chip
            key={`${t.qualified_name}-${t.model || ''}-${t.call_id || ''}`}
            size="small"
            label={t.model ? `${base} (${t.model})` : base}
            color="primary"
            variant="outlined"
          />
        );
      })}
    </Box>
  );
}
