import re
import html


_CODEBLOCK_RE = re.compile(r"```([\s\S]*?)```", re.MULTILINE)
_INLINE_CODE_RE = re.compile(r"`([^`]+)`")
_BOLD_MD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_BOLD_US_RE = re.compile(r"__(.+?)__", re.DOTALL)
_ITALIC_MD_RE = re.compile(r"(?<!\*)\*([^\*\n]+?)\*(?!\*)")
_ITALIC_US_RE = re.compile(r"(?<!_)_([^_\n]+?)_(?!_)")


def _extract_codeblocks(raw: str):
    blocks = []

    def _repl(match: re.Match) -> str:
        blocks.append(match.group(1))
        return f"{{{{CODEBLOCK_{len(blocks)-1}}}}}"

    return _CODEBLOCK_RE.sub(lambda m: _repl(m), raw), blocks


def convert_markdown_bold_to_html(text: str) -> str:
    """
    Convert lightweight Markdown (**bold**, *italic*, __bold__, _italic_, `code`, ```blocks```)
    to Telegram-safe HTML. Also strips stray single asterisks that Telegram would render oddly.
    """
    if not isinstance(text, str):
        return text

    # 1) Protect triple-backtick code blocks before any other substitutions
    with_placeholders, blocks = _extract_codeblocks(text)

    # 2) Escape HTML for safety
    escaped = html.escape(with_placeholders, quote=False)

    # 3) Inline code
    if "`" in escaped:
        escaped = _INLINE_CODE_RE.sub(r"<code>\1</code>", escaped)

    # 4) Bold (**text**, __text__)
    if "**" in escaped:
        escaped = _BOLD_MD_RE.sub(r"<b>\1</b>", escaped)
    if "__" in escaped:
        escaped = _BOLD_US_RE.sub(r"<b>\1</b>", escaped)

    # 5) Italic (*text*, _text_)
    if "*" in escaped:
        escaped = _ITALIC_MD_RE.sub(r"<i>\1</i>", escaped)
    if "_" in escaped:
        escaped = _ITALIC_US_RE.sub(r"<i>\1</i>", escaped)

    # 6) Remove any remaining stray asterisks that are not part of emphasis
    if "*" in escaped:
        escaped = escaped.replace("*", "")

    # 7) Restore code blocks as <pre><code>…</code></pre> with escaped content
    for i, code in enumerate(blocks):
        block_html = "<pre><code>{}</code></pre>".format(html.escape(code, quote=False))
        escaped = escaped.replace(f"{{{{CODEBLOCK_{i}}}}}", block_html)

    return escaped

