import React, { useMemo, useRef, useState } from 'react';
import {
  Box,
  Typography,
  IconButton,
  Tooltip,
  FormControl,
  InputLabel,
  OutlinedInput,
  InputAdornment,
  Popover,
  Switch,
  Chip,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import HelpOutlineIcon from '@mui/icons-material/HelpOutline';
import ExpandMoreIcon from '@mui/icons-material/ExpandMore';
import AgentIcon from '../../icons/AgentIcon';
import AgentTagsField, {
  normalizeAgentTags,
  useAgentTags,
} from '../../components/right_bar/AgentTagsField';
import type { SxProps, Theme } from '@mui/material/styles';
import {
  AGENT_CONSTRUCTOR_OUTLINED_INPUT_SX,
  SIDEBAR_HIDE_SCROLLBAR_SX,
  getDropdownChevronSx,
  getDropdownItemSx,
  getDropdownItemStateSx,
  getDropdownPopoverPaperSx,
} from '../../constants/menuStyles';

const ARTIFACTS_SWITCH_SX = {
  '& .MuiSwitch-switchBase.Mui-checked': { color: '#2196f3' },
  '& .MuiSwitch-switchBase.Mui-checked + .MuiSwitch-track': { bgcolor: 'rgba(33,150,243,0.5)' },
  '& .MuiSwitch-track': { bgcolor: 'rgba(255,255,255,0.2)' },
};

export interface SubagentConfig {
  enabled: boolean;
  allow_self: boolean;
  agent_ids: number[];
  /** Снимок имён (id → name) — для шаринга/галереи, когда агент не в списке. */
  agent_names: Record<number, string>;
  /** Агенты с любым из этих тегов вызываются кодом до ответа - всегда. */
  required_tag_ids: number[];
  /** true - только обязательные, tool subagent агенту не даётся. */
  required_only: boolean;
}

export interface SubagentAgentOption {
  id: number;
  name: string;
  /** Теги карточки (объекты {id, name} из API) - показываем рядом с именем. */
  tags?: unknown;
}

interface AgentSubagentsEditorProps {
  currentAgentId: number | 'new';
  config: SubagentConfig;
  onChange: (config: SubagentConfig) => void;
  agents: SubagentAgentOption[];
  readOnly?: boolean;
  maxSubagents?: number;
  panelChrome: {
    fgSubtle: string;
    fgMuted: string;
    hoverBg: string;
    isLight?: boolean;
  };
  categoryFieldSx?: SxProps<Theme>;
  /** Поле лимита сразу под «Режим с субагентами». */
  afterModeSlot?: React.ReactNode;
}

const DEFAULT_MAX_SUBAGENTS = 10;
/** Сколько чипов тегов показывать у агента в списке; остальные - в "+N". */
const TAG_CHIPS_LIMIT = 3;

export default function AgentSubagentsEditor({
  currentAgentId,
  config,
  onChange,
  agents,
  readOnly = false,
  maxSubagents = DEFAULT_MAX_SUBAGENTS,
  panelChrome,
  categoryFieldSx,
  afterModeSlot,
}: AgentSubagentsEditorProps) {
  const [popoverAnchor, setPopoverAnchor] = useState<HTMLElement | null>(null);
  const triggerRef = useRef<HTMLDivElement>(null);
  const darkFields = !panelChrome.isLight;
  const dropdownItemSx = useMemo(() => getDropdownItemSx(darkFields), [darkFields]);

  const options = useMemo(() => {
    const exclude = typeof currentAgentId === 'number' ? currentAgentId : null;
    return agents.filter((a) => a.id !== exclude && !config.agent_ids.includes(a.id));
  }, [agents, currentAgentId, config.agent_ids]);

  const byId = useMemo(() => new Map(agents.map((a) => [a.id, a])), [agents]);

  const resolveName = (id: number) => {
    const live = byId.get(id)?.name?.trim();
    if (live) return live;
    const names = config.agent_names || {};
    const snap = names[id] ?? (names as Record<string, string>)[String(id)];
    if (typeof snap === 'string' && snap.trim()) return snap.trim();
    return `Агент #${id}`;
  };

  // В конфиге хранятся id тегов, полю нужны имена - берём из справочника.
  // Тег, которого в справочнике уже нет (удалили), показываем как #id.
  const tagCatalog = useAgentTags();
  const requiredTagIds = config.required_tag_ids || [];
  const requiredTagValues = useMemo(
    () =>
      requiredTagIds.map((id) => {
        const found = tagCatalog.find((t) => t.id === id);
        return { id, name: found ? found.name : '#' + String(id) };
      }),
    [requiredTagIds, tagCatalog],
  );

  const setEnabled = (enabled: boolean) => {
    onChange({ ...config, enabled });
  };

  const setAllowSelf = (allow_self: boolean) => {
    onChange({ ...config, enabled: true, allow_self });
  };

  const addAgent = (id: number) => {
    if (config.agent_ids.length >= maxSubagents || config.agent_ids.includes(id)) return;
    const name = agents.find((a) => a.id === id)?.name?.trim();
    const nextNames = { ...(config.agent_names || {}) };
    if (name) nextNames[id] = name;
    onChange({
      ...config,
      enabled: true,
      agent_ids: [...config.agent_ids, id],
      agent_names: nextNames,
    });
    setPopoverAnchor(null);
  };

  const removeAgent = (id: number) => {
    const nextNames = { ...(config.agent_names || {}) };
    delete nextNames[id];
    delete (nextNames as Record<string, string>)[String(id)];
    onChange({
      ...config,
      agent_ids: config.agent_ids.filter((x) => x !== id),
      agent_names: nextNames,
    });
  };

  const nothingToSpawn =
    config.enabled &&
    !config.allow_self &&
    config.agent_ids.length === 0 &&
    requiredTagIds.length === 0;

  // Теги агента рядом с именем: по ним видно, кого подхватят обязательные.
  const renderTagChips = (raw: unknown) => {
    const tags = normalizeAgentTags(raw);
    if (!tags.length) return null;
    const shown = tags.slice(0, TAG_CHIPS_LIMIT);
    const hidden = tags.slice(TAG_CHIPS_LIMIT);
    const chipSx = {
      height: 16,
      maxWidth: 110,
      fontSize: '0.6rem',
      color: panelChrome.fgMuted,
      bgcolor: 'rgba(255,255,255,0.06)',
      '& .MuiChip-label': { px: 0.6 },
    };
    return (
      <Box component="span" sx={{ display: 'flex', gap: 0.5, flexWrap: 'wrap', minWidth: 0 }}>
        {shown.map((t) => (
          <Chip key={t.name} size="small" label={t.name} title={t.name} sx={chipSx} />
        ))}
        {hidden.length > 0 && (
          <Tooltip title={hidden.map((t) => t.name).join(', ')} arrow placement="top">
            <Chip size="small" label={'+' + String(hidden.length)} sx={chipSx} />
          </Tooltip>
        )}
      </Box>
    );
  };

  return (
    <Box sx={{ minWidth: 0 }}>
      {/* Режим с субагентами — как строка в разделе «Артефакты» */}
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', gap: 0.5, minWidth: 0, pr: 1 }}>
          <Typography variant="caption" sx={{ color: panelChrome.fgMuted, fontSize: '0.78rem' }}>
            Режим с субагентами
          </Typography>
          <Tooltip
            title="Изолированные дочерние запуски: модель вызывает tool subagent для подзадач. Подробный вывод инструментов остаётся у ребёнка, родителю возвращается итог."
            arrow
          >
            <HelpOutlineIcon sx={{ fontSize: 12, color: panelChrome.fgSubtle, cursor: 'help' }} />
          </Tooltip>
          <Chip
            size="small"
            label={`${config.agent_ids.length} / ${maxSubagents}`}
            sx={{
              height: 18,
              fontSize: '0.62rem',
              color: panelChrome.fgMuted,
              bgcolor: 'rgba(255,255,255,0.06)',
              '& .MuiChip-label': { px: 0.75 },
            }}
          />
        </Box>
        <Switch
          size="small"
          checked={config.enabled}
          disabled={readOnly}
          onChange={(e) => setEnabled(e.target.checked)}
          inputProps={{ 'aria-label': 'Режим с субагентами' }}
          sx={ARTIFACTS_SWITCH_SX}
        />
      </Box>

      {afterModeSlot ? <Box sx={{ mt: 1 }}>{afterModeSlot}</Box> : null}

      {config.enabled && (
        <Box sx={{ mt: 1, display: 'flex', flexDirection: 'column', gap: 1 }}>
          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
            <Typography variant="caption" sx={{ color: panelChrome.fgMuted, fontSize: '0.78rem' }}>
              Разрешить self-spawn (копия этого агента)
            </Typography>
            <Switch
              size="small"
              checked={config.allow_self}
              disabled={readOnly}
              onChange={(e) => setAllowSelf(e.target.checked)}
              inputProps={{ 'aria-label': 'Разрешить self-spawn' }}
              sx={ARTIFACTS_SWITCH_SX}
            />
          </Box>

          <AgentTagsField
            label="Обязательные теги"
            placeholder="Агенты с этими тегами вызываются всегда"
            allowCreate={false}
            readOnly={readOnly}
            darkFields={darkFields}
            value={requiredTagValues}
            onChange={(next) =>
              onChange({
                ...config,
                enabled: true,
                required_tag_ids: next
                  .map((t) => t.id)
                  .filter((id): id is number => typeof id === 'number'),
              })
            }
            help="Все доступные вам агенты с любым из этих тегов вызываются на каждое сообщение — до ответа этого агента, параллельно."
            sx={categoryFieldSx}
          />

          <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 1 }}>
            <Typography variant="caption" sx={{ color: panelChrome.fgMuted, fontSize: '0.78rem' }}>
              Только обязательные - без выбора этим агентом
            </Typography>
            <Switch
              size="small"
              checked={Boolean(config.required_only)}
              disabled={readOnly || requiredTagIds.length === 0}
              onChange={(e) => onChange({ ...config, required_only: e.target.checked })}
              inputProps={{ 'aria-label': 'Только обязательные теги' }}
              sx={ARTIFACTS_SWITCH_SX}
            />
          </Box>
          {config.required_only && requiredTagIds.length > 0 && (
            <Typography variant="caption" sx={{ color: panelChrome.fgSubtle, fontSize: '0.68rem' }}>
              Список субагентов ниже при этом не используется: агент отвечает только по результатам обязательных.
            </Typography>
          )}

          {config.agent_ids.map((id) => {
            const agent = byId.get(id);
            const label = resolveName(id);
            return (
              <Box
                key={id}
                sx={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: 0.75,
                  px: 0.5,
                  py: 0.25,
                  borderRadius: 1,
                  '&:hover': { bgcolor: panelChrome.hoverBg },
                }}
              >
                <AgentIcon sx={{ fontSize: 16, color: panelChrome.fgMuted }} />
                <Box sx={{ flex: 1, minWidth: 0, display: 'flex', flexDirection: 'column', gap: 0.25 }}>
                  <Typography variant="caption" sx={{ color: panelChrome.fgMuted, fontSize: '0.78rem' }} noWrap>
                    {label}
                  </Typography>
                  {renderTagChips(agent?.tags)}
                </Box>
                {!readOnly && (
                  <IconButton
                    size="small"
                    aria-label={`Убрать субагента ${label}`}
                    onClick={() => removeAgent(id)}
                    sx={{ color: panelChrome.fgSubtle, p: 0.25 }}
                  >
                    <CloseIcon sx={{ fontSize: 14 }} />
                  </IconButton>
                )}
              </Box>
            );
          })}

          {!readOnly && config.agent_ids.length < maxSubagents && (
            <Box ref={triggerRef}>
              <FormControl fullWidth size="small" sx={categoryFieldSx}>
                <InputLabel shrink>Добавить субагента</InputLabel>
                <OutlinedInput
                  readOnly
                  value=""
                  placeholder="Выберите агента"
                  onClick={(e) => setPopoverAnchor(e.currentTarget)}
                  endAdornment={
                    <InputAdornment position="end">
                      <ExpandMoreIcon sx={getDropdownChevronSx(darkFields)} />
                    </InputAdornment>
                  }
                  sx={{ ...AGENT_CONSTRUCTOR_OUTLINED_INPUT_SX, cursor: 'pointer' }}
                  label="Добавить субагента"
                />
              </FormControl>
              <Popover
                open={Boolean(popoverAnchor)}
                anchorEl={popoverAnchor}
                onClose={() => setPopoverAnchor(null)}
                anchorOrigin={{ vertical: 'bottom', horizontal: 'left' }}
                transformOrigin={{ vertical: 'top', horizontal: 'left' }}
                slotProps={{ paper: { sx: getDropdownPopoverPaperSx(popoverAnchor, darkFields) } }}
              >
                <Box sx={{ ...SIDEBAR_HIDE_SCROLLBAR_SX, maxHeight: 220, overflowY: 'auto', minWidth: 220, p: 0.5 }}>
                  {options.length === 0 ? (
                    <Typography variant="caption" sx={{ p: 1, display: 'block', opacity: 0.6 }}>
                      Нет доступных агентов
                    </Typography>
                  ) : (
                    options.map((agent) => (
                      <Box
                        key={agent.id}
                        onClick={() => addAgent(agent.id)}
                        sx={{
                          ...dropdownItemSx,
                          ...getDropdownItemStateSx(darkFields, false),
                        }}
                      >
                        <AgentIcon sx={{ fontSize: 14, opacity: 0.7 }} />
                        <Box sx={{ minWidth: 0, display: 'flex', flexDirection: 'column', gap: 0.25 }}>
                          <span>{agent.name}</span>
                          {renderTagChips(agent.tags)}
                        </Box>
                      </Box>
                    ))
                  )}
                </Box>
              </Popover>
            </Box>
          )}

          {nothingToSpawn && (
            <Typography variant="caption" sx={{ color: '#ff9800', fontSize: '0.72rem' }}>
              Включите self-spawn или добавьте хотя бы одного субагента.
            </Typography>
          )}
        </Box>
      )}
    </Box>
  );
}

export const EMPTY_SUBAGENT_CONFIG: SubagentConfig = {
  enabled: false,
  allow_self: true,
  agent_ids: [],
  agent_names: {},
  required_tag_ids: [],
  required_only: false,
};

/** Разбор config.subagents.agent_names (ключи могут быть строками из JSON). */
export function parseAgentNamesMap(raw: unknown): Record<number, string> {
  if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return {};
  const out: Record<number, string> = {};
  for (const [key, value] of Object.entries(raw as Record<string, unknown>)) {
    const id = Number(key);
    if (!Number.isFinite(id) || id <= 0) continue;
    const name = String(value ?? '').trim();
    if (name) out[id] = name;
  }
  return out;
}

/** Снимок имён для сохранения: live из списка + уже сохранённые. */
export function buildSubagentNamesSnapshot(
  agentIds: number[],
  agents: Array<{ id: number; name?: string }>,
  previous?: Record<number, string>,
): Record<number, string> {
  const byId = new Map(agents.map((a) => [a.id, a.name?.trim() || '']));
  const out: Record<number, string> = {};
  for (const id of agentIds) {
    const live = byId.get(id);
    const snap = previous?.[id];
    const name = (live && live.trim()) || (snap && snap.trim()) || '';
    if (name) out[id] = name;
  }
  return out;
}

export const MAX_SUBAGENTS_UI = DEFAULT_MAX_SUBAGENTS;
