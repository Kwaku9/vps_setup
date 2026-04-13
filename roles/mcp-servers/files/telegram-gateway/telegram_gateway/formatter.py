from __future__ import annotations

import html as html_module
import re

# Characters that must be escaped in Telegram MarkdownV2
_ESCAPE_CHARS = r"_*[]()~`>#+-=|{}.!\\"


def escape_markdown(text: str) -> str:
    """Escape special characters for Telegram MarkdownV2."""
    return re.sub(r"([" + re.escape(_ESCAPE_CHARS) + r"])", r"\\\1", text)


def format_code_block(code: str, language: str = "") -> str:
    """Wrap code in a Telegram HTML code block."""
    escaped = html_module.escape(code)
    if language:
        lang = html_module.escape(language)
        return f'<pre><code class="language-{lang}">{escaped}</code></pre>'
    return f"<pre>{escaped}</pre>"


def format_notification(title: str, body: str) -> str:
    """Format a notification with bold title and body."""
    return f"<b>{html_module.escape(title)}</b>\n\n{html_module.escape(body)}"


def format_thinking(text: str) -> str:
    """Format thinking/reasoning output — italic and collapsed."""
    lines = text.strip().split("\n")
    # Truncate long thinking to first few lines
    if len(lines) > 6:
        lines = lines[:6] + ["..."]
    escaped = html_module.escape("\n".join(lines))
    return f"<i>{escaped}</i>"


def format_tool_use(tool_name: str, tool_input: str) -> str:
    """Format a tool invocation — show tool name and input."""
    header = html_module.escape(f"Tool: {tool_name}")
    return f"<b>{header}</b>\n<pre>{html_module.escape(tool_input)}</pre>"


def format_tool_result(content: str) -> str:
    """Format tool/command output — monospace pre block."""
    # Truncate very long tool outputs
    if len(content) > 2000:
        content = content[:2000] + "\n... (truncated)"
    return f"<pre>{html_module.escape(content)}</pre>"


def _convert_markdown_to_html(text: str) -> str:
    """Convert GitHub-flavored markdown to Telegram-compatible HTML.

    Telegram HTML supports: <b>, <i>, <s>, <u>, <code>, <pre>,
    <a href="">, <blockquote>, <tg-spoiler>.

    Strategy:
    1. Extract code blocks/spans into placeholders (protect from conversion)
    2. HTML-escape the remaining text
    3. Convert markdown syntax to HTML tags
    4. Restore protected code blocks
    """
    placeholders: list[str] = []

    def _save_fenced(m: re.Match) -> str:
        idx = len(placeholders)
        lang = m.group(1) or ""
        code = html_module.escape(m.group(2))
        if lang:
            placeholders.append(
                f'<pre><code class="language-{html_module.escape(lang)}">'
                f"{code}</code></pre>"
            )
        else:
            placeholders.append(f"<pre>{code}</pre>")
        return f"\x00CB{idx}\x00"

    def _save_inline(m: re.Match) -> str:
        idx = len(placeholders)
        placeholders.append(f"<code>{html_module.escape(m.group(1))}</code>")
        return f"\x00CB{idx}\x00"

    result = re.sub(r"```(\w*)\n(.*?)\n```", _save_fenced, text, flags=re.DOTALL)
    result = re.sub(r"`([^`\n]+)`", _save_inline, result)

    # HTML-escape remaining text (only affects <, >, &, ", ')
    result = html_module.escape(result)

    # Headings: # text → bold (Telegram has no heading elements)
    result = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", result, flags=re.MULTILINE)

    # Bold-italic: ***text*** → <b><i>text</i></b>
    result = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", result)
    # Bold: **text** → <b>text</b>
    result = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", result)
    # Bold: __text__ → <b>text</b>
    result = re.sub(r"__(.+?)__", r"<b>\1</b>", result)
    # Italic: *text* (not bullet points, not inside words)
    result = re.sub(r"(?<!\w)\*(?!\s)(.+?)(?<!\s)\*(?!\w)", r"<i>\1</i>", result)
    # Italic: _text_ (not inside words like my_var_name)
    result = re.sub(r"(?<!\w)_(?!\s)(.+?)(?<!\s)_(?!\w)", r"<i>\1</i>", result)
    # Strikethrough: ~~text~~ → <s>text</s>
    result = re.sub(r"~~(.+?)~~", r"<s>\1</s>", result)

    # Links: [text](url) → <a href="url">text</a>
    result = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        result,
    )

    # Blockquotes: > text (> is &gt; after HTML escaping)
    result = re.sub(
        r"^&gt;\s?(.*)$", r"<blockquote>\1</blockquote>", result, flags=re.MULTILINE
    )
    # Merge adjacent blockquotes into one
    result = result.replace("</blockquote>\n<blockquote>", "\n")

    # Restore protected code blocks
    for idx, code_html in enumerate(placeholders):
        result = result.replace(f"\x00CB{idx}\x00", code_html)

    return result


def format_for_telegram(content: str, response_type: str = "text") -> str:
    """Format a response for Telegram based on its type.

    All output uses Telegram HTML parse mode.

    response_type values:
      - text:        GitHub-flavored markdown → Telegram HTML
      - code:        <pre> code block
      - thinking:    <i> italic reasoning
      - tool_use:    <b> tool name + <pre> input block
      - tool_result: <pre> monospace output block
      - log:         <pre> code block
    """
    if response_type == "code":
        # Try to detect language from first line
        lines = content.split("\n", 1)
        if len(lines) > 1 and lines[0].strip().isalpha() and len(lines[0].strip()) < 20:
            return format_code_block(lines[1], lines[0].strip())
        return format_code_block(content)
    if response_type == "thinking":
        return format_thinking(content)
    if response_type == "tool_use":
        return format_code_block(content)
    if response_type == "tool_result":
        return format_tool_result(content)
    if response_type == "log":
        return format_code_block(content, "")
    # Default: text — convert GitHub markdown to Telegram HTML
    return _convert_markdown_to_html(content)


def format_stderr(text: str) -> str:
    """Format stderr output as HTML with terminal styling.

    Uses HTML parse mode (not MarkdownV2) so we can use <pre> blocks.
    Telegram HTML supports: <b>, <i>, <pre>, <code>, <blockquote>.
    No CSS support, so we use structural elements for visual distinction.
    """
    escaped = html_module.escape(text)
    # Truncate very long stderr
    if len(escaped) > 3500:
        escaped = escaped[:3500] + "\n... (truncated)"
    return (
        "<blockquote><b>stderr</b></blockquote>\n"
        f"<pre>{escaped}</pre>"
    )


_SENSITIVE_PATTERNS = [
    # Bearer/API tokens
    (re.compile(r"(Bearer\s+)\S+", re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r'(-H\s+["\']Authorization:\s*Bearer\s+)\S+(["\'])', re.IGNORECASE), r"\1[REDACTED]\2"),
    # API key prefixes
    (re.compile(r"\b(sk-[a-zA-Z0-9_-]{10,})\b"), "[REDACTED-API-KEY]"),
    (re.compile(r"\b(sk-ant-api\S+)\b"), "[REDACTED-API-KEY]"),
    (re.compile(r"\b(sk-or-v1-\S+)\b"), "[REDACTED-API-KEY]"),
    (re.compile(r"\b(sk-proj-\S+)\b"), "[REDACTED-API-KEY]"),
    (re.compile(r"\b(sk-litellm-\S+)\b"), "[REDACTED-API-KEY]"),
    (re.compile(r"\b(xai-\S{20,})\b"), "[REDACTED-API-KEY]"),
    (re.compile(r"\b(gsk_\S{20,})\b"), "[REDACTED-API-KEY]"),
    (re.compile(r"\b(AIzaSy\S{20,})\b"), "[REDACTED-API-KEY]"),
    (re.compile(r"\b(re_[A-Za-z0-9_]{10,})\b"), "[REDACTED-API-KEY]"),
    # JWT tokens
    (re.compile(r"\beyJ[A-Za-z0-9_-]{20,}\.eyJ[A-Za-z0-9_-]{20,}\.[A-Za-z0-9_-]{20,}\b"), "[REDACTED-JWT]"),
    # Telegram bot tokens
    (re.compile(r"\b\d{8,}:[A-Za-z0-9_-]{30,}\b"), "[REDACTED-BOT-TOKEN]"),
    # Password/secret env vars
    (re.compile(r'(PASSWORD[=:]\s*["\']?)[^\s"\']+', re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r'(SECRET[=:]\s*["\']?)[^\s"\']+', re.IGNORECASE), r"\1[REDACTED]"),
    (re.compile(r'(TOKEN[=:]\s*["\']?)[^\s"\']{15,}', re.IGNORECASE), r"\1[REDACTED]"),
    # Docker/podman -e flags with secrets
    (re.compile(r'(-e\s+\w*(?:TOKEN|SECRET|PASSWORD|KEY)\s*=\s*["\']?)[^\s"\']{15,}', re.IGNORECASE), r"\1[REDACTED]"),
]


def sanitize_secrets(text: str) -> str:
    """Redact sensitive tokens, keys, passwords, and IDs from text."""
    result = text
    for pattern, replacement in _SENSITIVE_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def format_approval_result(prompt_text: str, status: str, decided_by: str = "") -> str:
    """Format an approval decision result as HTML."""
    escaped_prompt = html_module.escape(prompt_text)
    # Truncate long prompts
    if len(escaped_prompt) > 500:
        escaped_prompt = escaped_prompt[:500] + "..."
    status_upper = status.upper()
    icon = {"APPROVED": "APPROVED", "DENIED": "DENIED", "EXPIRED": "EXPIRED"}.get(
        status_upper, status_upper
    )
    by_text = f"\nBy: {html_module.escape(decided_by)}" if decided_by else ""
    return (
        f"<b>{icon}</b>\n\n"
        f"<pre>{escaped_prompt}</pre>"
        f"{by_text}"
    )


def chunk_message(text: str, max_len: int = 4096) -> list[str]:
    """Split a message into chunks that fit Telegram's 4096-char limit.

    Tries to split on newlines and respects HTML tag boundaries.
    Handles unclosed tags (<pre>, <b>, <i>, <s>, <code>, <blockquote>)
    by closing them at chunk end and reopening at next chunk start.
    """
    if len(text) <= max_len:
        return [text]

    # Tags that need balancing across chunks
    _BALANCE_TAGS = ["pre", "b", "i", "s", "code", "blockquote"]

    chunks: list[str] = []
    remaining = text

    while remaining:
        if len(remaining) <= max_len:
            chunks.append(remaining)
            break

        # Try to split at a newline before the limit
        split_at = remaining.rfind("\n", 0, max_len)
        if split_at == -1 or split_at < max_len // 2:
            split_at = max_len

        chunk = remaining[:split_at]
        remaining = remaining[split_at:].lstrip("\n")

        # Close unclosed HTML tags at end of chunk, reopen at start of next
        reopen = ""
        for tag in _BALANCE_TAGS:
            opens = len(re.findall(rf"<{tag}[\s>]", chunk)) + chunk.count(f"<{tag}>")
            closes = chunk.count(f"</{tag}>")
            if opens > closes:
                chunk += f"</{tag}>"
                reopen = f"<{tag}>" + reopen

        if reopen:
            remaining = reopen + remaining

        chunks.append(chunk)

    return chunks


def strip_html_tags(text: str) -> str:
    """Strip HTML tags and unescape entities for plaintext fallback."""
    return html_module.unescape(re.sub(r"<[^>]+>", "", text))
