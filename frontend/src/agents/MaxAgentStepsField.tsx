import React from 'react';
import { Box, IconButton, TextField, Tooltip } from '@mui/material';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import type { SxProps, Theme } from '@mui/material/styles';

interface MaxAgentStepsFieldProps {
  value: number | '';
  onChange: (value: number | '') => void;
  defaultSteps: number;
  maxSteps: number;
  readOnly?: boolean;
  panelChrome: {
    fgSubtle: string;
    fgMuted: string;
  };
  /** Как поле «Имя» в конструкторе (outlined + плавающая подпись). */
  sx?: SxProps<Theme>;
}

export default function MaxAgentStepsField({
  value,
  onChange,
  defaultSteps,
  maxSteps,
  readOnly = false,
  panelChrome,
  sx,
}: MaxAgentStepsFieldProps) {
  return (
    <Box sx={{ display: 'flex', alignItems: 'flex-start', gap: 0.5, width: '100%', minWidth: 0 }}>
      <TextField
        label="Максимальное количество шагов агента"
        fullWidth
        size="small"
        type="number"
        variant="outlined"
        disabled={readOnly}
        value={value}
        placeholder={`По умолчанию: ${defaultSteps}`}
        onChange={(e) => {
          const raw = e.target.value;
          if (raw === '') {
            onChange('');
            return;
          }
          const n = Number(raw);
          if (!Number.isFinite(n)) return;
          onChange(Math.max(1, Math.min(Math.trunc(n), maxSteps)));
        }}
        inputProps={{ min: 1, max: maxSteps, step: 1 }}
        sx={sx}
      />
      <Tooltip
        title={`Ограничивает шаги за один запуск (LLM-запрос или раунд инструментов). Пусто — глобальный лимит (${defaultSteps}). Максимум ${maxSteps}.`}
        arrow
        placement="top"
      >
        <IconButton
          size="small"
          aria-label="Справка: максимальное количество шагов агента"
          sx={{
            mt: 0.75,
            p: 0.35,
            color: panelChrome.fgSubtle,
            opacity: 0.7,
            '&:hover': { opacity: 1, bgcolor: 'transparent' },
          }}
        >
          <HelpOutlineIcon sx={{ fontSize: 16 }} />
        </IconButton>
      </Tooltip>
    </Box>
  );
}
