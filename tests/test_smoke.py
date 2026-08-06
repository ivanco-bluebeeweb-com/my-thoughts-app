"""Extension test suite for My Thoughts -- exercises the core flow
(create thought -> discuss -> propose action -> approve, graduate to
project, share + import) against imperal_sdk's MockContext.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from imperal_sdk.testing import MockContext

import main as m
from schemas import (
    CreateThoughtParams, AddThoughtMessageParams, ListThoughtsParams,
    GetThoughtParams, ArchiveThoughtParams,
    CreateProjectFromThoughtParams, ListProjectsParams,
    ProposeActionParams, ListProposedActionsParams, RespondToActionParams,
    CreateShareLinkParams, ListShareLinksParams, ForgetShareParams,
    ImportSharedThoughtParams,
)


# ──────────────────────────────────────────────────────────────────────────
# Thoughts — create / discuss / list / archive
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_thought_creates_first_message_when_given():
    ctx = MockContext()
    result = await m.create_thought(ctx, CreateThoughtParams(
        title="Should we build a referral program?",
        first_message="Thinking clients could refer other clients for a discount.",
    ))
    assert result.status == "success"
    thought_id = result.data["thought_id"]

    thought_doc = await ctx.store.get("thoughts", thought_id)
    assert thought_doc.data["title"] == "Should we build a referral program?"
    assert thought_doc.data["status"] == "open"
    assert thought_doc.data["message_count"] == 1

    msgs = await ctx.store.query("thought_messages", where={"thought_id": thought_id})
    assert len(msgs.data) == 1
    assert msgs.data[0].data["role"] == "user"


@pytest.mark.asyncio
async def test_create_thought_without_first_message_starts_at_zero():
    ctx = MockContext()
    result = await m.create_thought(ctx, CreateThoughtParams(title="Random idea, no detail yet"))
    assert result.status == "success"
    thought_id = result.data["thought_id"]
    thought_doc = await ctx.store.get("thoughts", thought_id)
    assert thought_doc.data["message_count"] == 0


@pytest.mark.asyncio
async def test_add_thought_message_increments_count_and_bumps_activity():
    ctx = MockContext()
    created = await m.create_thought(ctx, CreateThoughtParams(title="Pricing page redesign"))
    thought_id = created.data["thought_id"]

    result = await m.add_thought_message(ctx, AddThoughtMessageParams(
        thought_id=thought_id, role="webbee",
        text="I looked at 3 competitors -- want me to draft new copy?",
    ))
    assert result.status == "success"

    thought_doc = await ctx.store.get("thoughts", thought_id)
    assert thought_doc.data["message_count"] == 1
    assert thought_doc.data["last_activity_at"]


@pytest.mark.asyncio
async def test_add_thought_message_missing_thought_errors_cleanly():
    ctx = MockContext()
    result = await m.add_thought_message(ctx, AddThoughtMessageParams(
        thought_id="nonexistent", role="user", text="hi",
    ))
    assert result.status != "success"
    assert result.error_code == "THOUGHT_NOT_FOUND"


@pytest.mark.asyncio
async def test_list_thoughts_filters_by_status():
    ctx = MockContext()
    open_one = await m.create_thought(ctx, CreateThoughtParams(title="Open idea"))
    closed_one = await m.create_thought(ctx, CreateThoughtParams(title="Old idea"))
    await m.archive_thought(ctx, ArchiveThoughtParams(thought_id=closed_one.data["thought_id"]))

    open_result = await m.list_thoughts(ctx, ListThoughtsParams(status="open"))
    ids = [t.id for t in open_result.data.items]
    assert open_one.data["thought_id"] in ids
    assert closed_one.data["thought_id"] not in ids


@pytest.mark.asyncio
async def test_get_thought_returns_messages_in_order():
    ctx = MockContext()
    created = await m.create_thought(ctx, CreateThoughtParams(
        title="Newsletter idea", first_message="Maybe a monthly digest?",
    ))
    thought_id = created.data["thought_id"]
    await m.add_thought_message(ctx, AddThoughtMessageParams(
        thought_id=thought_id, role="webbee", text="I can draft one from your last 5 posts.",
    ))

    result = await m.get_thought(ctx, GetThoughtParams(thought_id=thought_id))
    assert result.status == "success"
    assert len(result.data.items) == 2


# ──────────────────────────────────────────────────────────────────────────
# Projects
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_project_from_thought_links_back():
    ctx = MockContext()
    created = await m.create_thought(ctx, CreateThoughtParams(title="New client onboarding flow"))
    thought_id = created.data["thought_id"]

    result = await m.create_project_from_thought(ctx, CreateProjectFromThoughtParams(
        thought_id=thought_id, name="Onboarding flow v1",
        description="Turn the discussion into a real checklist + Trello board.",
    ))
    assert result.status == "success"
    project_id = result.data["project_id"]

    thought_doc = await ctx.store.get("thoughts", thought_id)
    assert thought_doc.data["project_id"] == project_id

    projects = await m.list_projects(ctx, ListProjectsParams())
    assert any(p.id == project_id for p in projects.data.items)


@pytest.mark.asyncio
async def test_create_project_from_missing_thought_errors():
    ctx = MockContext()
    result = await m.create_project_from_thought(ctx, CreateProjectFromThoughtParams(
        thought_id="missing", name="X",
    ))
    assert result.status != "success"


# ──────────────────────────────────────────────────────────────────────────
# Proposed actions
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_propose_and_respond_to_action():
    ctx = MockContext()
    created = await m.create_thought(ctx, CreateThoughtParams(title="Referral program"))
    thought_id = created.data["thought_id"]

    proposed = await m.propose_action(ctx, ProposeActionParams(
        thought_id=thought_id,
        title="Create a Trello board to track referral program rollout",
        rationale="You've discussed this 3 times this week -- looks ready to move from idea to execution.",
        target_app="trello-connector", target_tool="create_board",
    ))
    assert proposed.status == "success"
    action_id = proposed.data["action_id"]

    listed = await m.list_proposed_actions(ctx, ListProposedActionsParams(status="pending"))
    assert any(a.id == action_id for a in listed.data.items)

    responded = await m.respond_to_action(ctx, RespondToActionParams(action_id=action_id, decision="approve"))
    assert responded.status == "success"
    assert responded.data["status"] == "approved"


@pytest.mark.asyncio
async def test_respond_to_missing_action_errors():
    ctx = MockContext()
    result = await m.respond_to_action(ctx, RespondToActionParams(action_id="missing", decision="approve"))
    assert result.status != "success"


# ──────────────────────────────────────────────────────────────────────────
# Background analysis -- test the per-user helper directly. This is the
# documented pattern for testing @ext.schedule fan-outs (see docs.imperal.io
# "@ext.schedule reference" -> Testing section): MockContext.store has no
# list_users, so the fan-out wrapper (daily_thought_scan) itself is not
# unit-testable without a real system-context store; _scan_one_user is the
# extracted per-user body, which IS directly testable with a plain
# MockContext standing in for an already-as_user()-scoped context.
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_scan_proposes_action_for_actionable_stale_thought():
    ctx = MockContext()
    ctx.ai.set_response(
        "TITLE:",
        "TITLE: Create a Trello board\nRATIONALE: You've discussed this enough to act.\nAPP: trello-connector",
    )
    created = await m.create_thought(ctx, CreateThoughtParams(
        title="Referral program", first_message="I think we should build a referral program for clients.",
    ))
    thought_id = created.data["thought_id"]
    # backdate last_activity_at so it reads as stale enough to scan
    await ctx.store.update("thoughts", thought_id, {"last_activity_at": "2020-01-01T00:00:00+00:00"})

    await m._scan_one_user(ctx)

    actions = await ctx.store.query("proposed_actions", where={"thought_id": thought_id})
    assert len(actions.data) == 1
    assert actions.data[0].data["status"] == "pending"


@pytest.mark.asyncio
async def test_scan_skips_non_actionable_thought():
    ctx = MockContext()
    created = await m.create_thought(ctx, CreateThoughtParams(
        title="Random musing", first_message="Just thinking out loud about colors today.",
    ))
    thought_id = created.data["thought_id"]
    await ctx.store.update("thoughts", thought_id, {"last_activity_at": "2020-01-01T00:00:00+00:00"})

    await m._scan_one_user(ctx)

    actions = await ctx.store.query("proposed_actions", where={"thought_id": thought_id})
    assert len(actions.data) == 0


@pytest.mark.asyncio
async def test_scan_does_not_double_propose_same_thought():
    ctx = MockContext()
    ctx.ai.set_response(
        "TITLE:",
        "TITLE: Create a Trello board\nRATIONALE: You've discussed this enough to act.\nAPP: trello-connector",
    )
    created = await m.create_thought(ctx, CreateThoughtParams(
        title="Referral program", first_message="We should build a referral program.",
    ))
    thought_id = created.data["thought_id"]
    await ctx.store.update("thoughts", thought_id, {"last_activity_at": "2020-01-01T00:00:00+00:00"})

    await m._scan_one_user(ctx)
    await ctx.store.update("thoughts", thought_id, {"last_activity_at": "2020-01-01T00:00:00+00:00"})
    await m._scan_one_user(ctx)

    actions = await ctx.store.query("proposed_actions", where={"thought_id": thought_id})
    assert len(actions.data) == 1


@pytest.mark.asyncio
async def test_scan_skips_recently_active_thought():
    ctx = MockContext()
    created = await m.create_thought(ctx, CreateThoughtParams(
        title="Referral program", first_message="We should build a referral program.",
    ))
    thought_id = created.data["thought_id"]
    # last_activity_at defaults to "now" from create_thought -- too fresh to scan
    await m._scan_one_user(ctx)

    actions = await ctx.store.query("proposed_actions", where={"thought_id": thought_id})
    assert len(actions.data) == 0


# ──────────────────────────────────────────────────────────────────────────
# Sharing -- self-contained snapshot codes (no cross-user store/context
# call anywhere: create_share_link and import_shared_thought each run in
# perfectly ordinary single-user context, exactly like every other
# @chat.function in this file).
# ──────────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_create_share_link_produces_decodable_code():
    ctx = MockContext()
    created = await m.create_thought(ctx, CreateThoughtParams(
        title="Idea worth sharing", first_message="Here's the pitch.",
    ))
    thought_id = created.data["thought_id"]

    result = await m.create_share_link(ctx, CreateShareLinkParams(thought_id=thought_id))
    assert result.status == "success"
    code = result.data["share_code"]
    assert code.startswith("myth1:")

    links = await m.list_share_links(ctx, ListShareLinksParams(thought_id=thought_id))
    assert len(links.data.items) == 1


@pytest.mark.asyncio
async def test_create_share_link_missing_thought_errors():
    ctx = MockContext()
    result = await m.create_share_link(ctx, CreateShareLinkParams(thought_id="missing"))
    assert result.status != "success"


@pytest.mark.asyncio
async def test_forget_share_removes_local_record():
    ctx = MockContext()
    created = await m.create_thought(ctx, CreateThoughtParams(title="Idea worth sharing"))
    thought_id = created.data["thought_id"]
    share = await m.create_share_link(ctx, CreateShareLinkParams(thought_id=thought_id))
    assert share.status == "success"

    links = await m.list_share_links(ctx, ListShareLinksParams(thought_id=thought_id))
    label = links.data.items[0].label

    forgotten = await m.forget_share(ctx, ForgetShareParams(label=label))
    assert forgotten.status == "success"

    links_after = await m.list_share_links(ctx, ListShareLinksParams(thought_id=thought_id))
    assert len(links_after.data.items) == 0


@pytest.mark.asyncio
async def test_import_shared_thought_creates_independent_local_copy():
    owner_ctx = MockContext()
    created = await m.create_thought(owner_ctx, CreateThoughtParams(
        title="Idea to share", first_message="Here's the full pitch text.",
    ))
    thought_id = created.data["thought_id"]
    await m.add_thought_message(owner_ctx, AddThoughtMessageParams(
        thought_id=thought_id, role="webbee", text="Sounds solid, let's flesh it out.",
    ))
    share = await m.create_share_link(owner_ctx, CreateShareLinkParams(thought_id=thought_id))
    code = share.data["share_code"]

    # Different Context entirely -- proves no cross-user store access happened;
    # the whole snapshot travelled inside the code string.
    importer_ctx = MockContext()
    result = await m.import_shared_thought(importer_ctx, ImportSharedThoughtParams(share_code=code))
    assert result.status == "success"
    new_id = result.data["thought_id"]

    imported_doc = await importer_ctx.store.get("thoughts", new_id)
    assert imported_doc.data["title"] == "Idea to share (shared)"
    assert imported_doc.data["imported_from_code"] is True
    assert imported_doc.data["message_count"] == 2

    msgs = await importer_ctx.store.query("thought_messages", where={"thought_id": new_id})
    assert len(msgs.data) == 2

    # Owner's original is untouched -- these are independent copies, not a live link.
    owner_doc = await owner_ctx.store.get("thoughts", thought_id)
    assert owner_doc.data["title"] == "Idea to share"


@pytest.mark.asyncio
async def test_import_shared_thought_rejects_malformed_code():
    ctx = MockContext()
    result = await m.import_shared_thought(ctx, ImportSharedThoughtParams(share_code="not-a-real-code"))
    assert result.status != "success"
    assert result.error_code == "SHARECODE_MALFORMED"


# ──────────────────────────────────────────────────────────────────────────
# converters — pure function unit tests
# ──────────────────────────────────────────────────────────────────────────


def test_looks_actionable_matches_action_language():
    from converters import looks_actionable
    assert looks_actionable(["I think we should build a referral program."])
    assert not looks_actionable(["Just thinking out loud about colors today."])


def test_encode_decode_share_code_roundtrips():
    from converters import encode_share_code, decode_share_code
    code = encode_share_code("Title", [{"role": "user", "text": "hi", "created_at": "t"}])
    decoded = decode_share_code(code)
    assert decoded["title"] == "Title"
    assert decoded["messages"][0]["text"] == "hi"


def test_decode_share_code_rejects_garbage():
    from converters import decode_share_code
    assert decode_share_code("garbage") is None
    assert decode_share_code("myth1:not-valid-base64!!!") is None
