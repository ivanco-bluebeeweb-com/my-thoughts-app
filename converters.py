"""Pure converters + heuristics for My Thoughts.

Kept separate from main.py so business-action handlers stay about the
action itself, not formatting/scoring detail. This module must NOT import
`ext`/`chat` back from main.py (one-way import only) — see main.py docstring.
"""
from __future__ import annotations

import base64
import json
import secrets as _pysecrets
from datetime import datetime, timezone

from schemas import (
    Thought, ThoughtMessage, Project, ProposedAction, ShareLink,
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def auto_title_from_message(text: str, max_len: int = 60) -> str:
    """Derive a short title from a first message, the same way ChatGPT titles
    an untitled chat -- first line, trimmed, ellipsised if long."""
    first_line = (text or "").strip().splitlines()[0] if (text or "").strip() else ""
    if not first_line:
        return "New thought"
    return first_line if len(first_line) <= max_len else first_line[: max_len - 1].rstrip() + "…"


def group_label_for(iso_ts: str) -> str:
    """Bucket a timestamp into the ChatGPT-style sidebar groups."""
    if not iso_ts:
        return "Older"
    try:
        ts = datetime.fromisoformat(iso_ts)
    except ValueError:
        return "Older"
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    days = (datetime.now(timezone.utc).date() - ts.date()).days
    if days <= 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    if days <= 7:
        return "Previous 7 days"
    return "Older"


def group_thoughts_by_recency(docs) -> list[tuple[str, list]]:
    """Group already-sorted (newest first) thought docs into ordered
    (label, [docs]) buckets, only including labels that have entries."""
    order = ["Today", "Yesterday", "Previous 7 days", "Older"]
    buckets: dict[str, list] = {label: [] for label in order}
    for d in docs:
        label = group_label_for(d.data.get("last_activity_at", ""))
        buckets[label].append(d)
    return [(label, buckets[label]) for label in order if buckets[label]]


def new_share_token() -> str:
    """URL-safe, unguessable share token. Not a credential — just an
    unguessable id — so plain secrets.token_urlsafe is the right tool here
    (ctx.secrets is for real per-user third-party credentials, not this)."""
    return _pysecrets.token_urlsafe(24)


def to_thought(doc) -> Thought:
    d = doc.data
    return Thought(
        id=doc.id,
        title=d.get("title", ""),
        status=d.get("status", "open"),
        message_count=d.get("message_count", 0),
        project_id=d.get("project_id", ""),
        imported_from_code=d.get("imported_from_code", False),
        created_at=d.get("created_at", ""),
        last_activity_at=d.get("last_activity_at", ""),
    )


def to_message(doc) -> ThoughtMessage:
    d = doc.data
    return ThoughtMessage(
        id=doc.id,
        thought_id=d.get("thought_id", ""),
        role=d.get("role", "user"),
        text=d.get("text", ""),
        created_at=d.get("created_at", ""),
    )


def to_project(doc) -> Project:
    d = doc.data
    return Project(
        id=doc.id,
        thought_id=d.get("thought_id", ""),
        name=d.get("name", ""),
        description=d.get("description", ""),
        status=d.get("status", "active"),
        external_ref=d.get("external_ref", ""),
        created_at=d.get("created_at", ""),
    )


def to_proposed_action(doc) -> ProposedAction:
    d = doc.data
    return ProposedAction(
        id=doc.id,
        thought_id=d.get("thought_id", ""),
        title=d.get("title", ""),
        rationale=d.get("rationale", ""),
        target_app=d.get("target_app", ""),
        target_tool=d.get("target_tool", ""),
        status=d.get("status", "pending"),
        created_at=d.get("created_at", ""),
    )


def to_share_link(doc) -> ShareLink:
    d = doc.data
    return ShareLink(
        id=doc.id,
        thought_id=d.get("thought_id", ""),
        label=d.get("label", ""),
        created_at=d.get("created_at", ""),
    )


# ──────────────────────────────────────────────────────────────────────────
# Share codes -- self-contained, portable snapshots. No cross-user store or
# context call exists on the platform (ctx.as_user/list_users are strictly
# __system__-context-only, and a real @ext.webhook runs as __webhook__, not
# __system__ -- verified against imperal_sdk/context.py directly), so a
# "share link" here means: the owner packs the thought's content INTO the
# code itself, in their own normal user context (fully legal), and the
# importing user's own chat function just decodes it locally. No server
# round-trip, no lookup, nothing to revoke once a code is handed out --
# that honesty is intentional and is stated back to the user in-product.
# ──────────────────────────────────────────────────────────────────────────

_SHARE_CODE_PREFIX = "myth1:"  # version tag, so a future v2 shape fails loudly instead of silently


def encode_share_code(title: str, messages: list[dict]) -> str:
    payload = {"title": title, "messages": messages}
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return _SHARE_CODE_PREFIX + base64.urlsafe_b64encode(raw).decode("ascii")


def decode_share_code(code: str) -> dict | None:
    code = code.strip()
    if not code.startswith(_SHARE_CODE_PREFIX):
        return None
    try:
        raw = base64.urlsafe_b64decode(code[len(_SHARE_CODE_PREFIX):].encode("ascii"))
        payload = json.loads(raw.decode("utf-8"))
    except Exception:
        return None
    if not isinstance(payload, dict) or "title" not in payload or "messages" not in payload:
        return None
    return payload


# ──────────────────────────────────────────────────────────────────────────
# Lightweight heuristics for background analysis — cheap, deterministic
# filtering of WHICH open thoughts are worth spending an LLM call on. The
# actual proposal text is written by the LLM in the schedule handler; this
# module only decides what is stale/idle-but-active enough to look at.
# ──────────────────────────────────────────────────────────────────────────

_ACTION_HINTS = (
    "should", "let's", "lets", "we need", "i need", "i want to build",
    "create a", "make a", "let's build", "plan", "todo", "next step",
    "нужно", "надо", "давай", "хочу сделать", "план",
)


def looks_actionable(messages: list[str]) -> bool:
    """Cheap keyword heuristic: does this thought's text contain language
    suggesting a concrete next step, as opposed to pure open musing?"""
    blob = " ".join(messages).lower()
    return any(hint in blob for hint in _ACTION_HINTS)


def hours_since(iso_ts: str, now: datetime | None = None) -> float:
    """Hours elapsed since an ISO timestamp; returns a large number if the
    timestamp is missing/unparseable so such records are treated as stale
    (never silently skipped)."""
    if not iso_ts:
        return 1e9
    try:
        ts = datetime.fromisoformat(iso_ts)
    except ValueError:
        return 1e9
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    return (now - ts).total_seconds() / 3600.0
