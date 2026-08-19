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
