"""Render a small Markdown subset without accepting HTML or remote links."""

import re
from html import escape

from markupsafe import Markup


def _inline(text: str) -> str:
    safe = escape(text)
    safe = re.sub(r"\*\*([^*\n]+)\*\*", r"<strong>\1</strong>", safe)
    return re.sub(r"\[(E[0-9]+|M[0-9a-f]{32})\]", r'<a href="#\1">[\1]</a>', safe)


def render_reply(text: str) -> Markup:
    """Support paragraphs, bold, lists and evidence links; escape everything else."""
    blocks: list[str] = []
    paragraph: list[str] = []
    list_kind: str | None = None
    # Separate compressed bullet items while leaving ordinary prose untouched.
    lines = []
    for line in text.splitlines():
        if re.match(r"^\s*[-*] ", line):
            lines.extend(re.split(r"\s+(?=- \*\*)", line))
        else:
            lines.append(line)
    for line in [*lines, ""]:
        match = re.match(r"^\s*(?:([-*]) |(\d{1,9})\. )(.+)$", line)
        kind = ("ul" if match[1] else "ol") if match else None
        if paragraph and (not line.strip() or match):
            blocks.append("<p>" + "<br>".join(_inline(part) for part in paragraph) + "</p>")
            paragraph.clear()
        if list_kind and kind != list_kind:
            blocks.append(f"</{list_kind}>")
            list_kind = None
        if match:
            if list_kind is None:
                blocks.append(f'<ol start="{int(match[2])}">' if kind == "ol" else "<ul>")
                list_kind = kind
            blocks.append("<li>" + _inline(match[3]) + "</li>")
        elif line.strip():
            paragraph.append(line)
    return Markup("".join(blocks))
