import React from 'react';
import {
  Box,
  Dialog,
  DialogContent,
  IconButton,
  Link,
  Typography,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { useNavigate } from 'react-router-dom';
import { RELEASE_NOTES_SHORT } from './releaseNotesShort';

type Props = {
  open: boolean;
  onClose: () => void;
  isDarkMode: boolean;
};

/** Диалог «Обновления»: краткие описания релизов + ссылка «Читать подробнее». */
export default function UpdatesDialog({ open, onClose, isDarkMode }: Props) {
  const navigate = useNavigate();

  const paperSx = {
    width: { xs: '94vw', sm: 'min(920px, 88vw)' },
    maxWidth: 920,
    m: 2,
    backgroundColor: isDarkMode ? '#2c2c2c' : '#ffffff',
    color: isDarkMode ? 'rgba(255,255,255,0.92)' : '#111',
    borderRadius: '12px',
    border: isDarkMode ? '1px solid rgba(255,255,255,0.08)' : '1px solid rgba(0,0,0,0.12)',
    boxShadow: isDarkMode ? '0 12px 40px rgba(0,0,0,0.55)' : '0 8px 28px rgba(0,0,0,0.16)',
    overflow: 'hidden',
  } as const;

  const linkSx = {
    fontSize: '0.9375rem',
    color: isDarkMode ? '#64b5f6' : '#1976d2',
    textDecorationColor: isDarkMode ? '#64b5f6' : '#1976d2',
    '&:hover': { color: isDarkMode ? '#90caf9' : '#1565c0' },
  } as const;

  const bodySx = {
    color: isDarkMode ? 'rgba(255,255,255,0.88)' : 'rgba(0,0,0,0.85)',
    fontSize: '0.9375rem',
    lineHeight: 1.55,
    '& .section-title': {
      fontWeight: 700,
      color: isDarkMode ? '#ffffff' : '#111',
      mt: 1.5,
      mb: 0.5,
    },
    '& .section-title:first-of-type': { mt: 0 },
    '& ul': { m: 0, pl: 2.5, mb: 0.25 },
    '& li': { mb: 0.35 },
  } as const;

  const dateSx = {
    flexShrink: 0,
    width: { sm: 132 },
    pt: { sm: 0.35 },
    fontSize: '0.8125rem',
    color: isDarkMode ? 'rgba(255,255,255,0.45)' : 'rgba(0,0,0,0.45)',
    whiteSpace: 'nowrap',
  } as const;

  const titleSx = {
    fontSize: '1.5rem',
    fontWeight: 700,
    color: isDarkMode ? '#ffffff' : '#111',
    mb: 1.75,
    lineHeight: 1.3,
  } as const;

  const readMoreSx = {
    display: 'inline-block',
    mt: 2.25,
    border: 'none',
    background: 'none',
    cursor: 'pointer',
    font: 'inherit',
    p: 0,
    textAlign: 'left' as const,
    ...linkSx,
  };

  const blockSx = {
    display: 'flex',
    flexDirection: { xs: 'column', sm: 'row' },
    alignItems: 'flex-start',
    gap: { xs: 1.5, sm: 4 },
    pb: 2.75,
  } as const;

  const dividerColor = isDarkMode ? 'rgba(255,255,255,0.14)' : 'rgba(0,0,0,0.12)';

  const openReleaseDetails = (version: string) => {
    onClose();
    navigate(`/docs/astrachat-release-${version}`);
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      maxWidth={false}
      fullWidth
      BackdropProps={{
        sx: { backgroundColor: isDarkMode ? 'rgba(0,0,0,0.55)' : 'rgba(0,0,0,0.4)' },
      }}
      PaperProps={{ sx: paperSx }}
    >
      <Box sx={{ px: { xs: 2.5, sm: 3.5 }, pt: 2, pb: 0 }}>
        <Box
          sx={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'space-between',
            pb: 0.5,
            borderBottom: `1px solid ${dividerColor}`,
          }}
        >
          <Typography
            component="span"
            sx={{
              fontSize: '1.75rem',
              fontWeight: 700,
              color: isDarkMode ? '#ffffff' : '#111',
              lineHeight: 1.15,
            }}
          >
            Обновления
          </Typography>
          <IconButton
            onClick={onClose}
            size="small"
            aria-label="Закрыть"
            sx={{
              color: isDarkMode ? 'rgba(255,255,255,0.5)' : 'rgba(0,0,0,0.45)',
              '&:hover': {
                backgroundColor: isDarkMode ? 'rgba(255,255,255,0.08)' : 'rgba(0,0,0,0.04)',
              },
            }}
          >
            <CloseIcon fontSize="small" />
          </IconButton>
        </Box>
      </Box>

      <DialogContent
        sx={{
          px: { xs: 2.5, sm: 3.5 },
          pt: 2.5,
          pb: 3,
          backgroundColor: 'transparent',
        }}
      >
        {RELEASE_NOTES_SHORT.map((release, index) => (
          <React.Fragment key={release.version}>
            {index > 0 && (
              <Box
                sx={{
                  height: 0,
                  border: 'none',
                  borderTop: `1px solid ${dividerColor}`,
                  mb: 2.75,
                }}
              />
            )}
            <Box sx={blockSx}>
              <Typography sx={dateSx}>{release.date}</Typography>
              <Box sx={{ flex: 1, minWidth: 0 }}>
                <Typography sx={titleSx}>{release.title}</Typography>
                <Box sx={bodySx}>
                  {release.sections.map((section) => (
                    <React.Fragment key={section.title}>
                      <Typography className="section-title" component="div">
                        {section.title}
                      </Typography>
                      <Box component="ul">
                        {section.items.map((item) => (
                          <li key={item}>{item}</li>
                        ))}
                      </Box>
                    </React.Fragment>
                  ))}
                </Box>
                <Link
                  component="button"
                  type="button"
                  underline="always"
                  onClick={() => openReleaseDetails(release.version)}
                  sx={readMoreSx}
                >
                  Читать подробнее.
                </Link>
              </Box>
            </Box>
          </React.Fragment>
        ))}

        <Box
          sx={{
            height: 0,
            border: 'none',
            borderTop: `1px solid ${dividerColor}`,
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
