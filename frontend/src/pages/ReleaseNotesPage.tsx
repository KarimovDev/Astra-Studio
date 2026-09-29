import React from 'react';
import StaticHtmlDocFrame from './StaticHtmlDocFrame';

const RELEASE_META: Record<string, { file: string; title: string }> = {
  '1.0': {
    file: 'astrachat-release-1.0.html',
    title: 'AstraChat 1.0 — подробности релиза',
  },
  '2.0': {
    file: 'astrachat-release-2.0.html',
    title: 'AstraChat 2.0 — подробности релиза',
  },
};

type Props = {
  /** Явная версия (предпочтительно): в URL с точкой (`1.0`) `:param` в React Router ненадёжен. */
  version: string;
};

/** Подробности релиза — HTML из public/static/user_documentation. */
export default function ReleaseNotesPage({ version }: Props) {
  const meta = RELEASE_META[version] || RELEASE_META['1.0'];
  const src = `${process.env.PUBLIC_URL || ''}/static/user_documentation/${meta.file}`;
  return <StaticHtmlDocFrame src={src} title={meta.title} />;
}
