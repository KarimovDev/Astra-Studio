import React from 'react';
import { Box, Switch, Tooltip, Typography } from '@mui/material';
import { HelpOutline as HelpIcon } from '@mui/icons-material';
import type { SxProps, Theme } from '@mui/material/styles';
import MaxAgentStepsField from './MaxAgentStepsField';

/**
 * «Общие настройки для цепочки агентов и субагентов» в конструкторе агента:
 * лимит шагов, скрытие промежуточных ответов, общий RAG.
 * Заголовок секции рисует конструктор (AgentConstructorPanel).
 */
interface AgentChainSubagentsSettingsProps {
  recursionLimit: number | '';
  onRecursionLimitChange: (value: number | '') => void;
  defaultGraphSteps: number;
  maxRecursionLimit: number;
  hideSequentialOutputs: boolean;
  onHideSequentialOutputsChange: (value: boolean) => void;
  sharedChainRag: boolean;
  onSharedChainRagChange: (value: boolean) => void;
  useParentSharedRag: boolean;
  onUseParentSharedRagChange: (value: boolean) => void;
  readOnly?: boolean;
  panelChrome: {
    fgSubtle: string;
    fgMuted: string;
  };
  fieldSx?: SxProps<Theme>;
}

export default function AgentChainSubagentsSettings({
  recursionLimit,
  onRecursionLimitChange,
  defaultGraphSteps,
  maxRecursionLimit,
  hideSequentialOutputs,
  onHideSequentialOutputsChange,
  sharedChainRag,
  onSharedChainRagChange,
  useParentSharedRag,
  onUseParentSharedRagChange,
  readOnly,
  panelChrome,
  fieldSx,
}: AgentChainSubagentsSettingsProps) {
  return (
    <Box sx={{ mt: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
      <MaxAgentStepsField
        value={recursionLimit}
        onChange={onRecursionLimitChange}
        defaultSteps={defaultGraphSteps}
        maxSteps={maxRecursionLimit}
        readOnly={readOnly}
        panelChrome={panelChrome}
        sx={fieldSx}
      />
      {[
        {
          label: 'Скрывать промежуточные ответы',
          help: 'В чате остаётся только финальный ответ цепочки или субагентов; промежуточные сообщения скрываются.',
          val: hideSequentialOutputs,
          onChange: onHideSequentialOutputsChange,
        },
        {
          label: 'Общий RAG для цепочки и субагентов',
          help: 'Субагенты и агенты цепочки используют общую RAG-память текущего запуска вместо изолированного контекста.',
          val: sharedChainRag,
          onChange: onSharedChainRagChange,
        },
        {
          label: 'Смотреть общий RAG родителя',
          help: 'Когда этого агента вызывают субагентом или он шаг цепочки, он видит базу знаний родителя, если у родителя включён «Общий RAG для цепочки и субагентов». Выключите - агент будет искать только в своих документах.',
          val: useParentSharedRag,
          onChange: onUseParentSharedRagChange,
        },
      ].map(({ label, help, val, onChange }) => (
        <Box key={label} sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
          <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0, pr: 1 }}>
            <Typography variant="caption" sx={{ color: 'rgba(255,255,255,0.7)', fontSize: '0.78rem' }}>
              {label}
            </Typography>
            <Tooltip title={help} arrow>
              <HelpIcon sx={{ fontSize: 12, color: 'rgba(255,255,255,0.25)' }} />
            </Tooltip>
          </Box>
          <Switch
            checked={val}
            disabled={readOnly}
            onChange={(e) => onChange(e.target.checked)}
            size="small"
            sx={{
              '& .MuiSwitch-switchBase.Mui-checked': { color: '#2196f3' },
              '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': { bgcolor: 'rgba(33,150,243,0.5)' },
              '& .MuiSwitch-track': { bgcolor: 'rgba(255,255,255,0.2)' },
            }}
          />
        </Box>
      ))}
    </Box>
  );
}
