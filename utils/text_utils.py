import re
import html


_BOLD_MD_PATTERN = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_CODE_MD_PATTERN = re.compile(r"`([^`]+)`")


def convert_markdown_bold_to_html(text: str) -> str:
    """
    Convert simple Markdown (**bold**, `code`) to Telegram HTML (<b>, <code>).

    - Escapes HTML first to avoid injection
    - Then replaces Markdown tokens with HTML tags
    """
    if not isinstance(text, str):
        return text
    escaped = html.escape(text, quote=False)
    # Inline code
    if "`" in escaped:
        escaped = _CODE_MD_PATTERN.sub(r"<code>\1</code>", escaped)
    # Bold
    if "**" in escaped:
        escaped = _BOLD_MD_PATTERN.sub(r"<b>\1</b>", escaped)
    return escaped

