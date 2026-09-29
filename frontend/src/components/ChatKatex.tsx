import React, { useMemo } from 'react';
import { Box } from '@mui/material';
import { renderKatexHtml } from '../utils/chatMath';

type Props = {
  latex: string;
  displayMode?: boolean;
};

/**
 * Изолированный рендер KaTeX. HTML генерирует только katex из нашего latex-ввода.
 */
export default function ChatKatex({ latex, displayMode = false }: Props) {
  const html = useMemo(
    () => renderKatexHtml(latex, displayMode),
    [latex, displayMode],
  );

  if (displayMode) {
    return (
      <Box
        component="div"
        className="astra-katex-display"
        sx={{
          my: 1.5,
          overflowX: 'auto',
          textAlign: 'center',
          '& .katex-display': { margin: 0 },
        }}
        dangerouslySetInnerHTML={{ __html: html }}
      />
    );
  }

  return (
    <Box
      component="span"
      className="astra-katex-inline"
      sx={{
        display: 'inline',
        '& .katex': { fontSize: '1.05em' },
      }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
}
