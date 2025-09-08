import re
import html


_BOLD_MD_PATTERN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)


def convert_markdown_bold_to_html(text: str) -> str:
    """
    Convert Markdown-style bold (**text**) to HTML (<b>text</b>) for Telegram HTML parse mode.

    Only transforms balanced pairs and leaves other content untouched.
    """
    if not isinstance(text, str):
        return text
    escaped = html.escape(text, quote=False)
    if "**" not in escaped:
        return escaped
    return _BOLD_MD_PATTERN.sub(r"<b>\1</b>", escaped)

