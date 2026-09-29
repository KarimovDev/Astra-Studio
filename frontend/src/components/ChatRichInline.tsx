import React from 'react';
import ChatInlineHtml from './ChatInlineHtml';
import ChatKatex from './ChatKatex';
import {
  type ChatMathBlock,
  hasMathPlaceholder,
  MATH_PLACEHOLDER_SPLIT_RE,
  MATH_PLACEHOLDER_ONE_RE,
} from '../utils/chatMath';

type Props = {
  text: string;
  mathBlocks?: ChatMathBlock[];
  keyPrefix?: string;
};

/**
 * Инлайн-контент чата: whitelist HTML + KaTeX-плейсхолдеры `%%ASTRA_MATH_N%%`.
 */
export default function ChatRichInline({ text, mathBlocks, keyPrefix = 'ri' }: Props) {
  if (!text) return null;

  if (!mathBlocks?.length || !hasMathPlaceholder(text)) {
    return <ChatInlineHtml text={text} keyPrefix={keyPrefix} />;
  }

  const parts = text.split(MATH_PLACEHOLDER_SPLIT_RE);
  return (
    <>
      {parts.map((part, i) => {
        if (!part) return null;
        const m = MATH_PLACEHOLDER_ONE_RE.exec(part);
        if (m) {
          const block = mathBlocks[Number(m[1])];
          if (!block) return null;
          return (
            <ChatKatex
              key={`${keyPrefix}-math-${i}`}
              latex={block.latex}
              displayMode={block.displayMode}
            />
          );
        }
        return (
          <ChatInlineHtml
            key={`${keyPrefix}-t-${i}`}
            text={part}
            keyPrefix={`${keyPrefix}-${i}`}
          />
        );
      })}
    </>
  );
}
