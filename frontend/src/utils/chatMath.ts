/**
 * Извлечение и рендер LaTeX/KaTeX в ответах чата.
 *
 * Поддерживает: $$...$$, $...$, \[...\], \(...\).
 * Не трогает code fences, inline `code`.
 * Валюта `$100` / `100$` не становится math.
 */

import katex from 'katex';

export type ChatMathBlock = {
  latex: string;
  displayMode: boolean;
};

/** ASCII-плейсхолдер: не конфликтует с JS replace `$1`/`$0` и markdown `__`. */
export function mathPlaceholder(index: number): string {
  return `%%ASTRA_MATH_${index}%%`;
}

export function hasMathPlaceholder(text: string): boolean {
  return text.includes('%%ASTRA_MATH_');
}

/** Разбивка строки на текст / math-токены. */
export const MATH_PLACEHOLDER_SPLIT_RE = /(%%ASTRA_MATH_\d+%%)/g;
export const MATH_PLACEHOLDER_ONE_RE = /^%%ASTRA_MATH_(\d+)%%$/;

/**
 * Валюта (префикс): `$100`, `$1,000.50`, `$5K`.
 * `(?![\$\d])` — не `$100$` / `$1$` (после суммы сразу `$` или ещё цифра).
 */
const CURRENCY_PREFIX_RE =
  /(?<![\\$])\$(?=(\d+(?:,\d{3})*(?:\.\d+)?(?:[KMBkmb])?)(?![\$\d]))/g;

/**
 * Валюта (постфикс): `100$`, `1,000.50$`, `5K$`.
 * `(?<![\$\d])` — не середина числа и не закрывающий `$` у `$100$`.
 */
const CURRENCY_POSTFIX_RE =
  /(?<![\$\d])(\d+(?:,\d{3})*(?:\.\d+)?(?:[KMBkmb])?)\$(?!\$)/g;

const CURRENCY_TOKEN = '\u0000ASTRA_CURRENCY\u0000';

function escapeCurrencyDollars(text: string, replacement: string): string {
  let s = text.replace(CURRENCY_PREFIX_RE, replacement);
  s = s.replace(CURRENCY_POSTFIX_RE, (_m, amount: string) => `${amount}${replacement}`);
  return s;
}

function protectRegions(
  text: string,
  pattern: RegExp,
): { text: string; regions: string[] } {
  const regions: string[] = [];
  const next = text.replace(pattern, (block) => {
    const token = `\u0000ASTRA_PROT_${regions.length}\u0000`;
    regions.push(block);
    return token;
  });
  return { text: next, regions };
}

function restoreRegions(text: string, regions: string[]): string {
  let out = text;
  regions.forEach((block, i) => {
    out = out.split(`\u0000ASTRA_PROT_${i}\u0000`).join(block);
  });
  return out;
}

function pushMath(
  blocks: ChatMathBlock[],
  latex: string,
  displayMode: boolean,
): string {
  const idx = blocks.length;
  blocks.push({ latex: latex.trim(), displayMode });
  return mathPlaceholder(idx);
}

/**
 * Вырезает math-фрагменты в плейсхолдеры до markdown/HTML-пайплайна.
 */
export function extractChatMath(raw: string): { text: string; blocks: ChatMathBlock[] } {
  if (!raw) return { text: raw, blocks: [] };
  if (!raw.includes('$') && !raw.includes('\\(') && !raw.includes('\\[')) {
    return { text: raw, blocks: [] };
  }

  const blocks: ChatMathBlock[] = [];

  // 1) Code fences / inline code
  const fences = protectRegions(raw, /```[\s\S]*?(?:```|$)/g);
  const inlines = protectRegions(fences.text, /`[^`\n]+`/g);
  let s = inlines.text;

  // 2) Display math ДО валюты ($$ не пересекается с $100)
  s = s.replace(/\$\$([\s\S]+?)\$\$/g, (_m, latex: string) => pushMath(blocks, latex, true));
  s = s.replace(/\\\[([\s\S]+?)\\\]/g, (_m, latex: string) => pushMath(blocks, latex, true));
  s = s.replace(/\\\(([\s\S]+?)\\\)/g, (_m, latex: string) => pushMath(blocks, latex, false));

  // 3) Валюта $100 / 100$ — чтобы не склеить «$100 и 50$» в одну формулу.
  //    `$1$` / `$0$` / `$100$` не трогаем (см. lookahead/lookbehind).
  s = escapeCurrencyDollars(s, CURRENCY_TOKEN);

  // 4) Inline $...$ (в т.ч. $0$, $1$, $e$, \pi)
  s = s.replace(
    /(?<!\\)\$(?!\$)((?:[^$\n\\]|\\.)+?)(?<!\\)\$(?!\$)/g,
    (_m, latex: string) => pushMath(blocks, latex, false),
  );

  s = s.split(CURRENCY_TOKEN).join('$');
  s = restoreRegions(s, inlines.regions);
  s = restoreRegions(s, fences.regions);

  return { text: s, blocks };
}

/** Рендер LaTeX → HTML (KaTeX). При ошибке — исходный текст в <code>. */
export function renderKatexHtml(latex: string, displayMode: boolean): string {
  try {
    return katex.renderToString(latex, {
      displayMode,
      throwOnError: false,
      strict: 'ignore',
      trust: false,
      output: 'html',
    });
  } catch {
    const safe = latex
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;');
    return `<code>${safe}</code>`;
  }
}

/**
 * Препроцесс для react-markdown + remark-math:
 * экранирует валюту `$100` / `100$`, чтобы не парсилась как math.
 */
export function preprocessArtifactLatex(content: string): string {
  if (!content || !content.includes('$')) return content;

  const fences = protectRegions(content, /```[\s\S]*?(?:```|$)/g);
  const inlines = protectRegions(fences.text, /`[^`\n]+`/g);
  let s = escapeCurrencyDollars(inlines.text, '\\$');
  s = restoreRegions(s, inlines.regions);
  s = restoreRegions(s, fences.regions);
  return s;
}
