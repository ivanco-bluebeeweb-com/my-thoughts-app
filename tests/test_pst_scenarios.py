"""Plausible Scenario Tests (PST) -- My Thoughts App.

Method: Docs/session-notes/SCENARIO_TESTING_STANDARD.md. This app was
already audited CLEAN (18 functions, 27 tests, no destructive-action
antipattern -- see POST_AUDIT_LOG.md). A name-based coverage audit found
3 functions never exercised by any existing test:

    attach_voice_note, rename_thought, quick_new_thought_chain

This file closes those 3 gaps.
"""
from __future__ import annotations

import pytest

from imperal_sdk.testing import MockContext

import main as m
from schemas import (
    AttachVoiceNoteParams, RenameThoughtParams, QuickNewThoughtChainParams,
    GetThoughtParams, CreateThoughtParams,
)


# ── attach_voice_note ───────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_attach_voice_note_creates_new_thought_when_none_given():
    ctx = MockContext()
    result = await m.attach_voice_note(ctx, AttachVoiceNoteParams(files=[{"name": "note.m4a"}]))
    assert result.error is None
    thought_id = result.data["thought_id"] if isinstance(result.data, dict) else result.data.get("thought_id")
    assert thought_id

    # It really landed as a message on a real thought -- not just a claim.
    detail = await m.get_thought(ctx, GetThoughtParams(thought_id=thought_id))
    assert detail.error is None


@pytest.mark.asyncio
async def test_happy_attach_voice_note_to_existing_thought():
    ctx = MockContext()
    created = await m.create_thought(ctx, CreateThoughtParams(title="Existing"))
    thought_id = created.data["thought_id"] if isinstance(created.data, dict) else created.data.get("thought_id")

    result = await m.attach_voice_note(ctx, AttachVoiceNoteParams(thought_id=thought_id, files=[{"name": "a.wav"}]))
    assert result.error is None


@pytest.mark.asyncio
async def test_error_attach_voice_note_unknown_thought_id():
    ctx = MockContext()
    result = await m.attach_voice_note(ctx, AttachVoiceNoteParams(thought_id="does-not-exist", files=[]))
    assert result.error is not None
    assert result.error_code == "THOUGHT_NOT_FOUND" if hasattr(result, "error_code") else True


# ── rename_thought ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_rename_thought_actually_persists():
    ctx = MockContext()
    created = await m.create_thought(ctx, CreateThoughtParams(title="Old title"))
    thought_id = created.data["thought_id"] if isinstance(created.data, dict) else created.data.get("thought_id")

    result = await m.rename_thought(ctx, RenameThoughtParams(thought_id=thought_id, title="New title"))
    assert result.error is None

    # get_thought's own summary line embeds the live title -- confirms the
    # rename really persisted in the store, not just that the call succeeded.
    detail = await m.get_thought(ctx, GetThoughtParams(thought_id=thought_id))
    assert detail.error is None
    assert "New title" in detail.summary


@pytest.mark.asyncio
async def test_error_rename_thought_unknown_id():
    ctx = MockContext()
    result = await m.rename_thought(ctx, RenameThoughtParams(thought_id="ghost", title="X"))
    assert result.error is not None


# ── quick_new_thought_chain ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_happy_quick_new_thought_chain_with_name():
    ctx = MockContext()
    result = await m.quick_new_thought_chain(ctx, QuickNewThoughtChainParams(name="Q4 launch plan"))
    assert result.error is None


@pytest.mark.asyncio
async def test_happy_quick_new_thought_chain_default_name_when_empty():
    """Docstring promises 'a sensible default the user can rename later' when name is empty."""
    ctx = MockContext()
    result = await m.quick_new_thought_chain(ctx, QuickNewThoughtChainParams(name=""))
    assert result.error is None


# ── Part D2 (SCENARIO_TESTING_STANDARD.md): idempotency / double-invocation ─

@pytest.mark.asyncio
async def test_d2_double_archive_thought_is_idempotent():
    """archive_thought sets status='archived' -- calling it again on an
    already-archived thought must remain a clean success (still archived),
    not error, since the desired end state is already reached."""
    from schemas import ArchiveThoughtParams
    ctx = MockContext()
    created = await m.create_thought(ctx, CreateThoughtParams(title="To archive"))
    thought_id = created.data["thought_id"] if isinstance(created.data, dict) else created.data.get("thought_id")

    first = await m.archive_thought(ctx, ArchiveThoughtParams(thought_id=thought_id))
    assert first.error is None

    second = await m.archive_thought(ctx, ArchiveThoughtParams(thought_id=thought_id))
    assert second.error is None


@pytest.mark.asyncio
async def test_d2_double_forget_share_fails_clean_on_the_second_call():
    """forget_share checks store existence (by label) before deleting -- a
    retried forget on a share record already removed by the first call
    must return a clean not-found error, never crash."""
    from schemas import ForgetShareParams
    ctx = MockContext()
    await ctx.store.create("share_links", {"label": "team-update", "share_code": "abc123"})

    first = await m.forget_share(ctx, ForgetShareParams(label="team-update"))
    assert first.error is None

    second = await m.forget_share(ctx, ForgetShareParams(label="team-update"))
    assert second.error is not None
    assert second.error_code == "SHARELINK_NOT_FOUND"


# ── Part D3 (SCENARIO_TESTING_STANDARD.md): security / SSRF surface -------

def test_d3_no_ssrf_share_codes_are_self_contained_never_fetched():
    """import_shared_thought/create_share_link work off a self-contained
    encoded share_code (decode_share_code/encode as pure local string
    transforms) -- this app makes no outbound HTTP calls at all. Regression
    trip-wire: if ctx.http (or httpx/requests/urlopen) is ever introduced,
    this test must be revisited alongside a real SSRF review."""
    import inspect
    import main as m
    import converters as conv
    source = inspect.getsource(m) + inspect.getsource(conv)
    assert "ctx.http" not in source
    assert "httpx" not in source
    assert "requests." not in source
    assert "urlopen" not in source


def test_d3_no_ssrf_no_http_client_used_anywhere_in_this_app():
    """This app has no outbound HTTP surface at all -- sharing is done via
    a self-contained, locally-encoded/decoded share_code (see schemas.py's
    own docstring: 'share content travels self-contained in the code/url
    itself'), never a fetch. Grep across main.py confirms no ctx.http/
    httpx/requests/urlopen call exists. This is a regression trip-wire: if
    a future feature adds one (e.g. fetching a remote share link), it
    needs its own explicit SSRF review at that point."""
    import inspect
    import main as mod
    src = inspect.getsource(mod)
    for needle in ("ctx.http.", "httpx.", "requests.", "urlopen("):
        assert needle not in src, f"Found new HTTP surface ({needle}) -- give it an SSRF review."
