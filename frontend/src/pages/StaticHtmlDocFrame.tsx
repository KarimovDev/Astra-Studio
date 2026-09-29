import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Box, useTheme } from '@mui/material';
import { useNavigate } from 'react-router-dom';
import {
  getWorkZoneBackgroundColor,
  getWorkZoneCustomImage,
} from '../constants/workZoneBackground';
import { useWorkZoneBgMode } from '../hooks/useWorkZoneBgMode';
import WorkZoneStarrySky from '../components/WorkZoneStarrySky';
import WorkZoneSnowfall from '../components/WorkZoneSnowfall';

/**
 * Показывает HTML-справку в рабочей зоне.
 * Грузим файл через fetch и отдаём в iframe как srcDoc:
 * - не упираемся в X-Frame-Options: DENY (nginx);
 * - не пересекаемся с FastAPI /docs (Swagger);
 * - пути /static/... резолвятся от origin приложения (gif/png работают).
 *
 * Важно: в srcDoc клик по href="#id" уходит в родительское SPA,
 * а href="/" с target="_parent" из about:srcdoc часто не срабатывает —
 * поэтому навигацию и якоря перехватываем из родителя после onLoad.
 *
 * Цвета текста/ссылок — из темы приложения; фон — как у рабочей зоны чата.
 */
function patchHtmlForFrame(text: string): string {
  // Ссылка «назад» — без target: клик перехватываем в родителе через navigate().
  return text.replace(
    /(<a\s[^>]*class="[^"]*back[^"]*"[^>]*)\s+target="[^"]*"/i,
    '$1',
  );
}

const HIDE_SCROLLBAR_CSS = `
html, body {
  scrollbar-width: none;
  -ms-overflow-style: none;
}
html::-webkit-scrollbar,
body::-webkit-scrollbar {
  width: 0;
  height: 0;
  display: none;
}
`;

function installDocClickGuard(doc: Document, onBack: () => void) {
  const onClick = (e: MouseEvent) => {
    const target = e.target as Element | null;
    const a = target?.closest?.('a') ?? null;
    if (!a) return;
    const href = a.getAttribute('href') || '';

    // «Вернуться в AstraChat» — SPA-навигация родителя (srcDoc + target=_parent ломается).
    if (a.classList.contains('back') || href === '/' || href === '') {
      e.preventDefault();
      e.stopPropagation();
      onBack();
      return;
    }

    if (href.charAt(0) !== '#') return;
    e.preventDefault();
    e.stopPropagation();
    const id = href.slice(1);
    if (!id) {
      doc.defaultView?.scrollTo({ top: 0, behavior: 'smooth' });
      return;
    }
    const el = doc.getElementById(id);
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'start' });
  };
  doc.addEventListener('click', onClick, true);
  return () => doc.removeEventListener('click', onClick, true);
}

function applyAppThemeToDoc(
  doc: Document,
  isDark: boolean,
  linkColor: string,
) {
  const root = doc.documentElement;
  root.style.setProperty('color-scheme', isDark ? 'dark' : 'light');
  // Прозрачный фон — сквозь iframe видна рабочая зона (цвет / картинка / анимация).
  root.style.setProperty('--bg', 'transparent');
  root.style.setProperty('--fg', isDark ? '#f2f2f2' : '#111111');
  root.style.setProperty('--muted', isDark ? '#9a9a9a' : '#777777');
  root.style.setProperty(
    '--border',
    isDark ? 'rgba(255, 255, 255, 0.14)' : 'rgba(0, 0, 0, 0.12)',
  );
  root.style.setProperty('--link', linkColor);
  root.style.setProperty(
    '--note-bg',
    isDark ? 'rgba(183, 28, 28, 0.25)' : 'rgba(211, 47, 47, 0.08)',
  );
  root.style.setProperty('--note-bd', isDark ? '#ef9a9a' : '#c62828');
  root.style.setProperty(
    '--th-bg',
    isDark ? 'rgba(255, 255, 255, 0.06)' : 'rgba(0, 0, 0, 0.04)',
  );
  if (doc.body) {
    doc.body.style.background = 'transparent';
    doc.body.style.color = isDark ? '#f2f2f2' : '#111111';
  }

  let styleEl = doc.getElementById('astra-doc-scrollbar-hide') as HTMLStyleElement | null;
  if (!styleEl) {
    styleEl = doc.createElement('style');
    styleEl.id = 'astra-doc-scrollbar-hide';
    styleEl.textContent = HIDE_SCROLLBAR_CSS;
    doc.head?.appendChild(styleEl);
  }
}

export default function StaticHtmlDocFrame({
  src,
  title,
}: {
  src: string;
  title: string;
}) {
  const theme = useTheme();
  const navigate = useNavigate();
  const isDarkMode = theme.palette.mode === 'dark';
  const linkColor = isDarkMode ? theme.palette.primary.light : theme.palette.primary.main;
  const workZoneMode = useWorkZoneBgMode();
  const workZoneBgColor = getWorkZoneBackgroundColor(isDarkMode, workZoneMode);
  const [workZoneCustomImage, setWorkZoneCustomImage] = useState(() => getWorkZoneCustomImage());

  const [html, setHtml] = useState('');
  const [error, setError] = useState('');
  const iframeRef = useRef<HTMLIFrameElement | null>(null);
  const removeGuardRef = useRef<(() => void) | null>(null);
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  useEffect(() => {
    const sync = () => setWorkZoneCustomImage(getWorkZoneCustomImage());
    window.addEventListener('interfaceSettingsChanged', sync);
    return () => window.removeEventListener('interfaceSettingsChanged', sync);
  }, []);

  const syncThemeIntoIframe = useCallback(() => {
    const doc = iframeRef.current?.contentDocument;
    if (!doc?.documentElement) return;
    applyAppThemeToDoc(doc, isDarkMode, linkColor);
  }, [isDarkMode, linkColor]);

  useEffect(() => {
    let cancelled = false;
    setHtml('');
    setError('');
    fetch(src, { credentials: 'same-origin' })
      .then((response) => {
        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }
        const type = response.headers.get('content-type') || '';
        if (type.includes('text/html') || type.includes('application/xhtml') || !type) {
          return response.text();
        }
        throw new Error(type);
      })
      .then((text) => {
        if (cancelled) return;
        setHtml(patchHtmlForFrame(text));
      })
      .catch(() => {
        if (!cancelled) setError('Не удалось загрузить документ справки');
      });
    return () => {
      cancelled = true;
      removeGuardRef.current?.();
      removeGuardRef.current = null;
    };
  }, [src]);

  // Тема могла смениться, пока iframe уже открыт.
  useEffect(() => {
    syncThemeIntoIframe();
  }, [syncThemeIntoIframe]);

  if (error) {
    return (
      <Box
        sx={{
          flex: 1,
          p: 3,
          color: 'text.secondary',
          backgroundColor: workZoneBgColor,
        }}
      >
        {error}
      </Box>
    );
  }

  return (
    <Box
      sx={{
        flex: 1,
        minHeight: 0,
        width: '100%',
        display: 'flex',
        flexDirection: 'column',
        position: 'relative',
        overflow: 'hidden',
        backgroundColor: workZoneBgColor,
        ...(workZoneMode === 'custom' && workZoneCustomImage
          ? {
              backgroundImage: `url("${workZoneCustomImage}")`,
              backgroundSize: 'cover',
              backgroundPosition: 'center',
              backgroundRepeat: 'no-repeat',
            }
          : {}),
      }}
    >
      {workZoneMode === 'starry' ? <WorkZoneStarrySky isDarkMode={isDarkMode} /> : null}
      {workZoneMode === 'snowfall' ? <WorkZoneSnowfall isDarkMode={isDarkMode} /> : null}

      {html ? (
        <Box
          component="iframe"
          ref={iframeRef}
          title={title}
          srcDoc={html}
          onLoad={() => {
            removeGuardRef.current?.();
            removeGuardRef.current = null;
            const doc = iframeRef.current?.contentDocument;
            if (doc) {
              applyAppThemeToDoc(doc, isDarkMode, linkColor);
              removeGuardRef.current = installDocClickGuard(doc, () => {
                navigateRef.current('/');
              });
            }
          }}
          sx={{
            position: 'relative',
            zIndex: 1,
            flex: 1,
            width: '100%',
            minHeight: 0,
            border: 'none',
            display: 'block',
            backgroundColor: 'transparent',
            // На случай, если скролл рисует сам iframe-элемент
            scrollbarWidth: 'none',
            msOverflowStyle: 'none',
            '&::-webkit-scrollbar': { display: 'none', width: 0, height: 0 },
          }}
        />
      ) : null}
    </Box>
  );
}
