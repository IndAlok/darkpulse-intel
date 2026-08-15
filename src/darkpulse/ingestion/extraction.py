from __future__ import annotations

from html.parser import HTMLParser

_MAX_BLOCKED_CHARS = 16_384


class _HtmlTextExtractor(HTMLParser):
    BLOCKED_TAGS = frozenset({"script", "style", "noscript", "svg", "template"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._blocked_depth = 0
        self._blocked_chars = 0
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.casefold() in self.BLOCKED_TAGS:
            self._blocked_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.casefold() in self.BLOCKED_TAGS and self._blocked_depth:
            self._blocked_depth -= 1
            self._blocked_chars = 0

    def handle_data(self, data: str) -> None:
        if not self._blocked_depth:
            self._parts.append(data)
            return
        self._blocked_chars += len(data)
        if self._blocked_chars > _MAX_BLOCKED_CHARS:
            self._blocked_depth = 0
            self._blocked_chars = 0
            self._parts.append(data)

    def text(self) -> str:
        return " ".join(" ".join(self._parts).split())


def html_to_text(source_bytes: bytes) -> str:
    extractor = _HtmlTextExtractor()
    extractor.feed(source_bytes.decode("utf-8", errors="replace"))
    extractor.close()
    return extractor.text()
