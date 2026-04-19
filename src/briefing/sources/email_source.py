"""Apple Mail email source via AppleScript."""

from __future__ import annotations

import re
import subprocess
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from ..models import EmailSourceConfig, SourceResult
from ..utils import shorten_text
from .types import SourceContext

_BODY_PREVIEW_CHARS = 400


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
        max_messages: int,
    ) -> list[dict]:
        """Return messages from Apple Mail matching the given criteria."""
        cutoff_days = max(1, (datetime.now(timezone.utc) - cutoff).days)
        script = _build_script(account, mailboxes, cutoff_days, max_messages)
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

    try:
        messages = adapter.fetch_messages(
            account=config.account,
            mailboxes=config.mailboxes,
            cutoff=cutoff,
            max_messages=max_msgs,
        )
    except (subprocess.SubprocessError, subprocess.TimeoutExpired, RuntimeError, OSError) as exc:
        return SourceResult(
            source_type="email",
            label=config.label,
            content="",
            required=config.required,
            status="error",
            error=str(exc),
        )

    # Apply sender filter (Python-side; Apple Mail's sender field is not email-only)
    if config.sender_emails_any:
        sender_set = {e.lower() for e in config.sender_emails_any}
        messages = [m for m in messages if m.get("from_email", "").lower() in sender_set]

    # Apply subject regex filter (OR logic, case-insensitive)
    if config.subject_regex_any:
        patterns = [re.compile(r, re.IGNORECASE) for r in config.subject_regex_any]
        messages = [
            m for m in messages if any(p.search(m.get("subject", "")) for p in patterns)
        ]

    # Sort by date descending then cap
    messages.sort(key=lambda m: m.get("date", ""), reverse=True)
    messages = messages[:max_msgs]

    content = _format_messages(messages, config.label, days, config.mailboxes)
    limited, truncated = shorten_text(content, max_chars)

    return SourceResult(
        source_type="email",
        label=config.label,
        content=limited,
        required=config.required,
        status="ok",
        truncated=truncated,
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
            name = msg.get("from_name") or msg.get("from_email", "")
            email = msg.get("from_email", "")
            subject = msg.get("subject", "").strip()
            body = msg.get("body", "").strip()
            body_part = f" — {body}" if body else ""
            sender = f"**{name}** ({email})" if email else f"**{name}**"
            lines.append(f"- {sender} {time_str}: {subject}{body_part}")
        lines.append("")

    return "\n".join(lines).rstrip()


def _build_script(
    account: str | None,
    mailboxes: list[str],
    cutoff_days: int,
    max_messages: int,
) -> str:
    account_filter = account.replace('"', '\\"') if account else ""
    if mailboxes:
        mbox_items = ", ".join(f'"{m.replace(chr(34), chr(92) + chr(34))}"' for m in mailboxes)
        mbox_list = "{" + mbox_items + "}"
    else:
        mbox_list = "{}"

    return f"""\
tell application "Mail"
    set cutoffDate to (current date) - ({cutoff_days} * days)
    set accountFilter to "{account_filter}"
    set mailboxFilter to {mbox_list}
    set maxCount to {max_messages}
    set msgCount to 0
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
                            if msgCount < maxCount then
                                set d to date received of msg
                                set yr to year of d as string
                                set mo to (month of d as integer)
                                set dy to day of d
                                set hr to hours of d
                                set mn to minutes of d
                                if mo < 10 then set moS to "0" & mo else set moS to (mo as string)
                                if dy < 10 then set dyS to "0" & dy else set dyS to (dy as string)
                                if hr < 10 then set hrS to "0" & hr else set hrS to (hr as string)
                                if mn < 10 then set mnS to "0" & mn else set mnS to (mn as string)
                                set dateStr to yr & "-" & moS & "-" & dyS & " " & hrS & ":" & mnS
                                set rawBody to content of msg
                                if (count of characters in rawBody) > {_BODY_PREVIEW_CHARS} then
                                    set rawBody to text 1 through {_BODY_PREVIEW_CHARS} of rawBody
                                end if
                                set bodyParas to paragraphs of rawBody
                                set cleanBody to ""
                                repeat with para in bodyParas
                                    set cleanBody to cleanBody & (para as string) & " "
                                end repeat
                                set output to output & "<<MSG>>" & linefeed & "date: " & dateStr & linefeed & "from: " & (sender of msg) & linefeed & "subject: " & (subject of msg) & linefeed & "body: " & cleanBody & linefeed
                                set msgCount to msgCount + 1
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
