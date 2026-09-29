
"""Артефакты и файлы из ответов субагентов - в итоговый ответ родителя.

Были в realtime/handlers.py. Зовутся после цикла инструментов родителя -
и в обычном чате, и в multi-LLM.
"""

from __future__ import annotations

from backend.settings.logging import get_logger

log = get_logger(__name__)


def subagent_artifact_blocks(result) -> list:
    """Все :::artifact-блоки из ответа субагента, включая незакрытые.

    Модель ставит закрывающий code-fence и забывает про :::. Рендер в её
    собственном чате это прощает, строгая регулярка - нет: блок терялся, и
    родитель пересказывал слайды текстом. Незакрытый блок берём до следующего
    заголовка или до конца ответа и закрываем сами (и fence, если открыт).
    Голый html-документ в fence без заголовка заворачиваем в text/html.
    """
    import hashlib
    import re

    fence = chr(96) * 3
    text = str(result or "")
    if not text.strip():
        return []
    header_re = re.compile(r":::artifact\{[^}\n]*\}")
    close_re = re.compile(r"\n:::[ \t]*(?:\n|$)")
    ident_re = re.compile(r"identifier=[\"']([^\"']+)[\"']")
    heads = list(header_re.finditer(text))
    blocks: list = []
    for i, h in enumerate(heads):
        stop = heads[i + 1].start() if i + 1 < len(heads) else len(text)
        m = close_re.search(text, h.end(), stop)
        if m:
            blocks.append(text[h.start() : m.end()].strip())
            continue
        body = text[h.start() : stop].rstrip()
        fences = sum(1 for ln in body.splitlines() if ln.strip().startswith(fence))
        if fences % 2:
            body += "\n" + fence
        im = ident_re.search(h.group(0))
        log.info(
            "[subagent] артефакт %s без закрывающего :::, закрыт принудительно",
            im.group(1) if im else "?",
        )
        blocks.append(body + "\n:::")
    if blocks:
        return blocks
    fence_re = re.compile(fence + r"html[ \t]*\n([\s\S]*?)\n" + fence, re.IGNORECASE)
    for fm in fence_re.finditer(text):
        html = fm.group(1)
        low = html.lstrip().lower()
        if not (low.startswith("<!doctype html") or low.startswith("<html")):
            continue
        tm = re.search(r"<title>([^<]{1,120})</title>", html, re.IGNORECASE)
        title = ((tm.group(1).strip() if tm else "") or "HTML-документ субагента").replace('"', "'")
        ident = "subagent-html-" + hashlib.md5(html.encode("utf-8", "ignore")).hexdigest()[:8]
        log.info("[subagent] html-документ от субагента без :::artifact обёрнут в %s", ident)
        blocks.append(
            ':::artifact{identifier="' + ident + '" type="text/html" title="' + title + '"}\n'
            + fence + "html\n" + html + "\n" + fence + "\n:::"
        )
    return blocks


def carry_subagent_artifacts(response, mcp_tool_events) -> str:
    """Артефакты и файлы из ответов субагентов - в итоговый ответ родителя.

    Ребёнок отдаёт :::artifact-блок (схема, презентация, график) и ссылки на
    файлы текстом tool-результата; родитель их пересказывает, и до рендера
    они не доходят. Блоки, чьего identifier в ответе нет, дописываем в конец
    как есть; ссылки, которых в ответе нет, - блоком «Файлы:». Воспроизвёл
    родитель сам - второго не будет.
    """
    text = str(response or "")
    try:
        import re

        if not mcp_tool_events:
            return text
        ident_re = re.compile(r"identifier=[\"']([^\"']+)[\"']")
        have = set(ident_re.findall(text))
        extra: list = []
        links: list = []
        seen_urls: set = set()
        for ev in mcp_tool_events:
            if not isinstance(ev, dict) or ev.get("type") != "mcp_tool_end":
                continue
            if ev.get("tool") == "subagent":
                for block in subagent_artifact_blocks(ev.get("result")):
                    m = ident_re.search(block)
                    ident = m.group(1) if m else block
                    if ident in have:
                        continue
                    have.add(ident)
                    extra.append(block.strip())
            for link in ev.get("download_urls") or []:
                if not isinstance(link, dict):
                    continue
                url = str(link.get("url") or "")
                if url and url not in text and url not in seen_urls:
                    seen_urls.add(url)
                    links.append(dict(link))
        if not extra and not links:
            return text
        out = text
        if extra:
            out = (out.rstrip() + "\n\n" + "\n\n".join(extra)).strip()
        if links:
            from backend.mcp.result_parser import append_download_links_to_content

            out = append_download_links_to_content(out, links)
        log.info(
            "[subagent] в ответ родителя добавлено: артефактов=%s файлов=%s",
            len(extra),
            len(links),
        )
        return out
    except Exception:
        log.debug("[subagent] не удалось перенести артефакты", exc_info=True)
        return text
