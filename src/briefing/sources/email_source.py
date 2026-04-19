"""Apple Mail email source via AppleScript."""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from ..models import EmailSourceConfig, SourceResult
from ..utils import shorten_text
from .types import SourceContext

_RAW_BODY_FETCH_CHARS = 3000
_BODY_PREVIEW_CHARS = 2000
_PARAGRAPH_SEPARATOR = "__BRIEFING_PARA__"
_REPLY_HEADER_PATTERNS = (
    re.compile(r"^on .+ wrote:$", re.IGNORECASE),
    re.compile(r"^from:\s", re.IGNORECASE),
    re.compile(r"^sent:\s", re.IGNORECASE),
    re.compile(r"^to:\s", re.IGNORECASE),
    re.compile(r"^subject:\s", re.IGNORECASE),
    re.compile(r"^(begin )?forwarded message:?$", re.IGNORECASE),
    re.compile(r"^-{2,}\s*original message\s*-{2,}$", re.IGNORECASE),
    re.compile(r"^-{2,}\s*forwarded message\s*-{2,}$", re.IGNORECASE),
)
_SIGNATURE_MARKERS = ("--", "__", "sent from my ")


class MailAdapter:
    """Thin wrapper around osascript for querying Apple Mail."""

    def __init__(self, timeout: int) -> None:
        self._timeout = timeout

    def _run_script(self, script: str) -> tuple[int, str, str]:
        result = subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            text=True,
            timeout=self._timeout,
        )
        return result.returncode, result.stdout, result.stderr

    def validate(self) -> tuple[bool, str]:
        """Check that Apple Mail can be scripted by the current user."""
        script = 'tell application "Mail" to return name of account 1'
        try:
            code, _stdout, stderr = self._run_script(script)
        except subprocess.TimeoutExpired:
            return False, "Apple Mail automation timed out"
        if code == 0:
            return True, "Apple Mail access OK"
        err = stderr.lower()
        if "not running" in err or "application mail" in err:
            return False, "Apple Mail is not running — open Mail.app before running briefing"
        return False, (
            "Apple Mail automation permission required: "
            "System Settings → Privacy & Security → Automation"
        )

    def fetch_messages(
        self,
        account: str | None,
        mailboxes: list[str],
        cutoff: datetime,
        email_addresses: list[str] | None = None,
    ) -> list[dict]:
        """Return messages from Apple Mail matching the given criteria."""
        cutoff_days = max(1, (datetime.now(timezone.utc) - cutoff).days)
        script = _build_script(account, mailboxes, cutoff_days, email_addresses or [])
        code, stdout, stderr = self._run_script(script)
        if code != 0:
            raise RuntimeError(stderr.strip() or "osascript returned non-zero exit code")
        return _parse_output(stdout)


def collect_email_sources(
    context: SourceContext,
    configs: list[EmailSourceConfig],
) -> list[SourceResult]:
    """Collect one SourceResult per EmailSourceConfig."""
    adapter = MailAdapter(timeout=context.settings.email.request_timeout_seconds)
    return [_collect_one(context, config, adapter) for config in configs]


def _collect_one(
    context: SourceContext,
    config: EmailSourceConfig,
    adapter: MailAdapter,
) -> SourceResult:
    days = config.history_days or context.settings.email.history_days
    max_msgs = config.max_messages or context.settings.email.max_messages
    max_chars = config.max_characters or context.settings.email.max_characters
    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    label = f"Emails related to {context.series.display_name}"

    try:
        messages = adapter.fetch_messages(
            account=config.account,
            mailboxes=config.mailboxes,
            cutoff=cutoff,
            email_addresses=config.email_addresses,
        )
    except (subprocess.SubprocessError, subprocess.TimeoutExpired, RuntimeError, OSError) as exc:
        return SourceResult(
            source_type="email",
            label=label,
            content="",
            required=config.required,
            status="error",
            error=str(exc),
        )

    # Filter by email address — match against from_email or any to_email (OR logic)
    if config.email_addresses:
        addr_set = {e.lower() for e in config.email_addresses}
        messages = [
            m for m in messages
            if m.get("from_email", "").lower() in addr_set
            or addr_set.intersection(e.lower() for e in m.get("to_emails", []))
        ]

    # Apply subject regex filter (OR logic, case-insensitive)
    if config.subject_regex_any:
        patterns = [re.compile(r, re.IGNORECASE) for r in config.subject_regex_any]
        messages = [
            m for m in messages if any(p.search(m.get("subject", "")) for p in patterns)
        ]

    # Sort by date descending then cap
    messages.sort(key=lambda m: m.get("date", ""), reverse=True)
    messages = messages[:max_msgs]

    content = _format_messages(messages, label, days, config.mailboxes)
    limited, truncated = shorten_text(content, max_chars)

    return SourceResult(
        source_type="email",
        label=label,
        content=limited,
        required=config.required,
        status="ok",
        truncated=truncated,
        metadata={"empty": not bool(messages)},
    )


def _format_messages(
    messages: list[dict],
    label: str,
    days: int,
    mailboxes: list[str],
) -> str:
    if not messages:
        return ""

    scope = ", ".join(mailboxes) if mailboxes else "all mailboxes"
    day_word = "day" if days == 1 else "days"
    lines = [f"# {label}", f"Last {days} {day_word} · {scope}", ""]

    by_date: dict[str, list[dict]] = defaultdict(list)
    for msg in messages:
        date_part = msg.get("date", "")[:10]
        by_date[date_part].append(msg)

    for date_str in sorted(by_date, reverse=True):
        try:
            dt = datetime.strptime(date_str, "%Y-%m-%d")
            heading = dt.strftime("%-d %B %Y")
            heading = f"{dt.strftime('%A')} {heading}"
        except ValueError:
            heading = date_str
        lines.append(f"## {heading}")
        lines.append("")
        for msg in by_date[date_str]:
            time_str = msg.get("date", "")[11:16]
            from_name = msg.get("from_name") or msg.get("from_email", "")
            from_email = msg.get("from_email", "")
            to_emails = msg.get("to_emails", [])
            subject = msg.get("subject", "").strip()
            body = msg.get("body", "").strip().replace("\n", " / ")
            body_part = f" — {body}" if body else ""
            sender = f"**{from_name}** ({from_email})" if from_email else f"**{from_name}**"
            if to_emails:
                to_part = f" → {', '.join(to_emails)}"
            else:
                to_part = ""
            lines.append(f"- {sender}{to_part} {time_str}: {subject}{body_part}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _build_script(
    account: str | None,
    mailboxes: list[str],
    cutoff_days: int,
    email_addresses: list[str],
) -> str:
    account_filter = account.replace('"', '\\"') if account else ""
    if mailboxes:
        mbox_items = ", ".join(f'"{m.replace(chr(34), chr(92) + chr(34))}"' for m in mailboxes)
        mbox_list = "{" + mbox_items + "}"
    else:
        mbox_list = "{}"
    if email_addresses:
        address_items = ", ".join(
            f'"{email.lower().replace(chr(34), chr(92) + chr(34))}"'
            for email in email_addresses
        )
        address_list = "{" + address_items + "}"
    else:
        address_list = "{}"

    return f"""\
tell application "Mail"
    set cutoffDate to (current date) - ({cutoff_days} * days)
    set accountFilter to "{account_filter}"
    set mailboxFilter to {mbox_list}
    set addressFilter to {address_list}
    set output to ""
    set targetAccounts to every account
    repeat with acct in targetAccounts
        if accountFilter is "" or (name of acct) is accountFilter then
            set allMailboxes to every mailbox of acct
            repeat with mbox in allMailboxes
                if (count of mailboxFilter) is 0 or (name of mbox) is in mailboxFilter then
                    try
                        set msgs to (messages of mbox whose date received >= cutoffDate)
                        repeat with msg in msgs
                            set includeMsg to ((count of addressFilter) is 0)
                            if not includeMsg then
                                set senderText to (sender of msg) as string
                                repeat with addr in addressFilter
                                    if senderText contains (addr as string) then
                                        set includeMsg to true
                                        exit repeat
                                    end if
                                end repeat
                            end if
                            set recips to to recipients of msg
                            if not includeMsg then
                                repeat with r in recips
                                    set recipAddress to (address of r) as string
                                    repeat with addr in addressFilter
                                        if recipAddress is (addr as string) then
                                            set includeMsg to true
                                            exit repeat
                                        end if
                                    end repeat
                                    if includeMsg then exit repeat
                                end repeat
                            end if
                            if not includeMsg then
                                -- Skip body extraction for unrelated messages to keep large mailboxes fast.
                                set recips to {{}}
                            else
                            set d to date received of msg
                            set yr to year of d as string
                            set mo to (month of d as integer)
                            set dy to day of d
                            set hr to hours of d
                            set mn to minutes of d
                            set moS to text -2 thru -1 of ("0" & (mo as string))
                            set dyS to text -2 thru -1 of ("0" & (dy as string))
                            set hrS to text -2 thru -1 of ("0" & (hr as string))
                            set mnS to text -2 thru -1 of ("0" & (mn as string))
                            set dateStr to yr & "-" & moS & "-" & dyS & " " & hrS & ":" & mnS
                            set rawBody to content of msg
                            if (count of characters in rawBody) > {_RAW_BODY_FETCH_CHARS} then
                                set rawBody to text 1 through {_RAW_BODY_FETCH_CHARS} of rawBody
                            end if
                            set bodyParas to paragraphs of rawBody
                            set cleanBody to ""
                            repeat with para in bodyParas
                                if cleanBody is "" then
                                    set cleanBody to para as string
                                else
                                    set cleanBody to cleanBody & "{_PARAGRAPH_SEPARATOR}" & (para as string)
                                end if
                            end repeat
                            set toAddrs to ""
                            repeat with r in recips
                                set toAddrs to toAddrs & (address of r) & ","
                            end repeat
                            set output to output & "<<MSG>>" & linefeed & "date: " & dateStr & linefeed & "from: " & (sender of msg) & linefeed & "to: " & toAddrs & linefeed & "subject: " & (subject of msg) & linefeed & "body: " & cleanBody & linefeed
                            end if
                        end repeat
                    end try
                end if
            end repeat
        end if
    end repeat
    return output
end tell"""


def _parse_output(output: str) -> list[dict]:
    messages = []
    for block in output.split("<<MSG>>"):
        block = block.strip()
        if not block:
            continue
        msg: dict[str, str] = {}
        for line in block.splitlines():
            if ": " in line:
                key, _, value = line.partition(": ")
                msg[key.strip()] = value.strip()
        if "date" not in msg:
            continue
        from_raw = msg.get("from", "")
        msg["from_name"], msg["from_email"] = _parse_sender(from_raw)
        to_raw = msg.get("to", "")
        msg["to_emails"] = [a.strip().lower() for a in to_raw.split(",") if a.strip()]
        msg["body"] = _extract_body_preview(msg.get("body", ""))
        messages.append(msg)
    return messages


def _parse_sender(raw: str) -> tuple[str, str]:
    """Parse 'Name <email@addr>' or 'email@addr' into (name, email)."""
    raw = raw.strip()
    match = re.match(r'^(.*?)\s*<([^>]+)>\s*$', raw)
    if match:
        name = match.group(1).strip().strip('"')
        email = match.group(2).strip().lower()
        return name, email
    return "", raw.lower()


def _extract_body_preview(raw: str) -> str:
    """Keep the new content from an email body and trim obvious quoted history."""
    if not raw:
        return ""
    normalized = raw.replace(_PARAGRAPH_SEPARATOR, "\n")
    normalized = normalized.replace("\r\n", "\n").replace("\r", "\n")
    lines = [line.rstrip() for line in normalized.splitlines()]
    cleaned: list[str] = []

    for line in lines:
        stripped = line.strip()
        if _is_reply_boundary(stripped):
            break
        if stripped.startswith((">", "|")):
            break
        if stripped.lower().startswith(_SIGNATURE_MARKERS):
            break
        if not stripped:
            if cleaned and cleaned[-1] != "":
                cleaned.append("")
            continue
        cleaned.append(stripped)

    body = "\n".join(cleaned).strip()
    if not body:
        body = normalized.strip()
    body = re.sub(r"\n{3,}", "\n\n", body)
    if len(body) > _BODY_PREVIEW_CHARS:
        body = body[:_BODY_PREVIEW_CHARS].rstrip()
    return body


def _is_reply_boundary(line: str) -> bool:
    if not line:
        return False
    return any(pattern.match(line) for pattern in _REPLY_HEADER_PATTERNS)
