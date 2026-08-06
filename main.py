"""My Thoughts — a Webbee-to-user discussion space.

You bring an idea, we discuss it over time in a thread ("Thought"), and
Webbee quietly analyzes the accumulated context in the background
(@ext.schedule) to propose concrete next actions tied to real installed
apps. A Thought can graduate into a Project, and can be shared with
another Imperal user as a self-contained, read-only snapshot code.

Boundaries (by design):
- does NOT execute proposed actions itself — it records a suggestion
  (target_app/target_tool/rationale); the user approves, then Webbee (in
  chat, with the real tool) carries it out. This app is the ideas layer,
  not an automation executor.
- does NOT support live multi-user co-editing of a Thought, and sharing is
  NOT a live link. The platform has no cross-user store/context primitive
  reachable from ordinary handler code (ctx.as_user/list_users are strictly
  __system__-context-only, and a real @ext.webhook runs as __webhook__, not
  __system__ — verified directly against the SDK's context guard). So a
  share is a snapshot packed INTO the code itself at the moment of sharing;
  the importer decodes it locally. No lookup, no revoke once handed out —
  see the sharing section below for the full reasoning.

Everything that registers against `ext`/`chat` (chat functions, panels,
schedule) lives directly in this file. schemas.py and converters.py are
pure leaf modules imported one-way from here — nothing imports back from
main.py, which is what the platform's deploy loader requires (it loads
main.py by path, not as a package, so any handler module trying to import
`chat`/`ext` back out of main.py ends up talking to a second, empty copy
of this module).
"""
from __future__ import annotations

from imperal_sdk import ActionResult, Extension, ChatExtension, ui

from schemas import (
    Thought, ThoughtList, ThoughtMessage, ThoughtMessageList,
    Project, ProjectList, ProposedAction, ProposedActionList,
    ShareLink, ShareLinkList,
    CreateThoughtParams, StartThoughtParams, AddThoughtMessageParams, AttachVoiceNoteParams,
    ListThoughtsParams,
    GetThoughtParams, ArchiveThoughtParams, RenameThoughtParams,
    CreateProjectFromThoughtParams, QuickNewProjectParams, ListProjectsParams,
    ListProposedActionsParams, ProposeActionParams, RespondToActionParams,
    CreateShareLinkParams, ListShareLinksParams, ForgetShareParams,
    ImportSharedThoughtParams,
)
from converters import (
    now_iso, to_thought, to_message, to_project,
    to_proposed_action, to_share_link, looks_actionable, hours_since,
    encode_share_code, decode_share_code,
    auto_title_from_message, group_thoughts_by_recency,
)

ext = Extension(
    "my-thoughts-app",
    version="0.1.0",
    display_name="My Thoughts",
    description=(
        "Discuss your ideas with Webbee over time, turn discussions into "
        "projects, and share select discussions with other users. Webbee "
        "analyzes your thoughts in the background and proposes concrete "
        "next actions across your other apps."
    ),
    icon="icon.svg",
    actions_explicit=True,
)

chat = ChatExtension(
    ext, "my_thoughts",
    description="Create and manage discussion threads (Thoughts), graduate them into Projects, review Webbee's proposed actions, and share Thoughts with other users.",
)


# ──────────────────────────────────────────────────────────────────────────
# Thoughts — the discussion threads themselves
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "create_thought",
    description="Start a new Thought — a discussion thread for one idea. Optionally seed it with the user's first message.",
    action_type="write",
    effects=["thought.create"],
)
async def create_thought(ctx, params: CreateThoughtParams) -> ActionResult:
    now = now_iso()
    doc = await ctx.store.create("thoughts", {
        "title": params.title,
        "status": "open",
        "message_count": 0,
        "project_id": "",
        "imported_from_code": False,
        "created_at": now,
        "last_activity_at": now,
    })
    if params.first_message.strip():
        await ctx.store.create("thought_messages", {
            "thought_id": doc.id,
            "role": "user",
            "text": params.first_message,
            "created_at": now,
        })
        await ctx.store.update("thoughts", doc.id, {"message_count": 1, "last_activity_at": now})
    return ActionResult.success(
        summary=f"Started a new Thought: {params.title}",
        data={"thought_id": doc.id},
        refresh_panels=["thoughts"],
    )


@chat.function(
    "add_thought_message",
    description="Append a message to an existing Thought's discussion — either the user's own words or Webbee's reply, keeping the running conversation.",
    action_type="write",
    effects=["thought.update"],
)
async def add_thought_message(ctx, params: AddThoughtMessageParams) -> ActionResult:
    thought = await ctx.store.get("thoughts", params.thought_id)
    if thought is None:
        return ActionResult.error("Thought not found.", code="THOUGHT_NOT_FOUND")
    now = now_iso()
    await ctx.store.create("thought_messages", {
        "thought_id": params.thought_id,
        "role": params.role if params.role in ("user", "webbee") else "user",
        "text": params.text,
        "created_at": now,
    })
    new_count = int(thought.data.get("message_count", 0)) + 1
    await ctx.store.update("thoughts", params.thought_id, {
        "message_count": new_count,
        "last_activity_at": now,
    })
    return ActionResult.success(
        summary="Message added to the Thought.",
        data={"thought_id": params.thought_id, "message_count": new_count},
        refresh_panels=["thoughts", "thought_detail"],
    )


@chat.function(
    "attach_voice_note",
    description=(
        "Attach an uploaded audio recording to a Thought as a voice-note "
        "message. STUB: this platform has no live microphone-capture UI "
        "primitive, so this only accepts an already-recorded audio file the "
        "user uploads (not live dictation) -- and it does NOT transcribe it, "
        "there is no speech-to-text wired up. It records that a voice note "
        "was attached so the thread shows it happened; use add_thought_message "
        "for actual text content."
    ),
    action_type="write",
    effects=["thought.update"],
)
async def attach_voice_note(ctx, params: AttachVoiceNoteParams) -> ActionResult:
    now = now_iso()
    thought_id = params.thought_id
    if not thought_id:
        thought_doc = await ctx.store.create("thoughts", {
            "title": "Voice note",
            "status": "open",
            "message_count": 0,
            "project_id": "",
            "imported_from_code": False,
            "created_at": now,
            "last_activity_at": now,
        })
        thought_id = thought_doc.id
    else:
        thought_doc = await ctx.store.get("thoughts", thought_id)
        if thought_doc is None:
            return ActionResult.error("Thought not found.", code="THOUGHT_NOT_FOUND")

    n = len(params.files) if params.files else 0
    label = f"🎤 [Voice note attached -- {n} file(s), not transcribed yet]" if n else "🎤 [Voice note attached]"
    await ctx.store.create("thought_messages", {
        "thought_id": thought_id,
        "role": "user",
        "text": label,
        "created_at": now,
    })
    new_count = int(thought_doc.data.get("message_count", 0)) + 1
    await ctx.store.update("thoughts", thought_id, {
        "message_count": new_count,
        "last_activity_at": now,
    })
    return ActionResult.success(
        summary="Voice note attached (not transcribed -- no speech-to-text on this platform yet).",
        data={"thought_id": thought_id, "message_count": new_count},
        refresh_panels=["thoughts", "thought_detail"],
    )


@chat.function(
    "list_thoughts",
    description="List the user's Thoughts (discussion threads), optionally filtered by status.",
    action_type="read",
    data_model=ThoughtList,
)
async def list_thoughts(ctx, params: ListThoughtsParams) -> ActionResult:
    where = {"status": params.status} if params.status else None
    page = await ctx.store.query("thoughts", where=where, order_by="-last_activity_at", limit=params.limit)
    items = [to_thought(d) for d in page.data]
    return ActionResult.success(
        summary=f"{len(items)} thought(s).",
        data=ThoughtList(items=items, total=len(items)),
    )


@chat.function(
    "get_thought",
    description="Read one Thought's full discussion history (all messages in order).",
    action_type="read",
    data_model=ThoughtMessageList,
)
async def get_thought(ctx, params: GetThoughtParams) -> ActionResult:
    thought = await ctx.store.get("thoughts", params.thought_id)
    if thought is None:
        return ActionResult.error("Thought not found.", code="THOUGHT_NOT_FOUND")
    page = await ctx.store.query("thought_messages", where={"thought_id": params.thought_id}, order_by="created_at", limit=500)
    items = [to_message(d) for d in page.data]
    return ActionResult.success(
        summary=f"Thought '{thought.data.get('title','')}' — {len(items)} message(s).",
        data=ThoughtMessageList(items=items, total=len(items)),
    )


@chat.function(
    "archive_thought",
    description="Archive a Thought — keeps it, but takes it out of active background analysis and the default list.",
    action_type="write",
    effects=["thought.update"],
)
async def archive_thought(ctx, params: ArchiveThoughtParams) -> ActionResult:
    thought = await ctx.store.get("thoughts", params.thought_id)
    if thought is None:
        return ActionResult.error("Thought not found.", code="THOUGHT_NOT_FOUND")
    await ctx.store.update("thoughts", params.thought_id, {"status": "archived"})
    return ActionResult.success(
        summary="Thought archived.",
        data={"thought_id": params.thought_id},
        refresh_panels=["thoughts"],
    )


@chat.function(
    "rename_thought",
    description="Rename a Thought's title.",
    action_type="write",
    effects=["thought.update"],
)
async def rename_thought(ctx, params: RenameThoughtParams) -> ActionResult:
    thought = await ctx.store.get("thoughts", params.thought_id)
    if thought is None:
        return ActionResult.error("Thought not found.", code="THOUGHT_NOT_FOUND")
    await ctx.store.update("thoughts", params.thought_id, {"title": params.title})
    return ActionResult.success(
        summary=f"Renamed to '{params.title}'.",
        data={"thought_id": params.thought_id, "title": params.title},
        refresh_panels=["thoughts", "thought_detail"],
    )


# ──────────────────────────────────────────────────────────────────────────
# Projects — what a Thought graduates into
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "create_project_from_thought",
    description="Graduate a Thought into a Project — the moment an idea becomes something to actually execute. Does not by itself create anything in Trello/Asana/etc — pair it with a real tool call on the target app if the user wants that.",
    action_type="write",
    effects=["project.create", "thought.update"],
)
async def create_project_from_thought(ctx, params: CreateProjectFromThoughtParams) -> ActionResult:
    thought = await ctx.store.get("thoughts", params.thought_id)
    if thought is None:
        return ActionResult.error("Thought not found.", code="THOUGHT_NOT_FOUND")
    now = now_iso()
    proj = await ctx.store.create("projects", {
        "thought_id": params.thought_id,
        "name": params.name,
        "description": params.description,
        "status": "active",
        "external_ref": "",
        "created_at": now,
    })
    await ctx.store.update("thoughts", params.thought_id, {"project_id": proj.id})
    return ActionResult.success(
        summary=f"Project '{params.name}' created from thought.",
        data={"project_id": proj.id, "thought_id": params.thought_id},
        refresh_panels=["thoughts", "thought_detail"],
    )


@chat.function(
    "quick_new_project",
    description=(
        "Start a brand-new Project directly, with no existing Thought yet -- "
        "for when the user just wants an empty project shell to fill in, the "
        "same way a fresh 'New chat' starts empty. Creates a companion Thought "
        "under the hood (Projects always grow from a Thought in this app's "
        "model) and immediately graduates it, so the user lands on one ready "
        "project, not a two-step flow."
    ),
    action_type="write",
    effects=["thought.create", "project.create"],
)
async def quick_new_project(ctx, params: QuickNewProjectParams) -> ActionResult:
    now = now_iso()
    name = params.name.strip() or "New project"
    thought_doc = await ctx.store.create("thoughts", {
        "title": name,
        "status": "open",
        "message_count": 0,
        "project_id": "",
        "imported_from_code": False,
        "created_at": now,
        "last_activity_at": now,
    })
    proj = await ctx.store.create("projects", {
        "thought_id": thought_doc.id,
        "name": name,
        "description": "",
        "status": "active",
        "external_ref": "",
        "created_at": now,
    })
    await ctx.store.update("thoughts", thought_doc.id, {"project_id": proj.id})
    return ActionResult.success(
        summary=f"Started a new project: {name}",
        data={"project_id": proj.id, "thought_id": thought_doc.id},
        refresh_panels=["thoughts", "thought_detail"],
    )


@chat.function(
    "list_projects",
    description="List projects that were graduated from Thoughts.",
    action_type="read",
    data_model=ProjectList,
)
async def list_projects(ctx, params: ListProjectsParams) -> ActionResult:
    page = await ctx.store.query("projects", order_by="-created_at", limit=params.limit)
    items = [to_project(d) for d in page.data]
    return ActionResult.success(summary=f"{len(items)} project(s).", data=ProjectList(items=items, total=len(items)))


# ──────────────────────────────────────────────────────────────────────────
# Proposed actions — background analysis output, and the same shape when
# Webbee proposes something live in chat
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "propose_action",
    description="Record a concrete next-action suggestion tied to a Thought, for the user to approve or dismiss later. Use this when reasoning about a Thought live in chat and you spot something worth doing — the same record background analysis also produces.",
    action_type="write",
    effects=["proposed_action.create"],
)
async def propose_action(ctx, params: ProposeActionParams) -> ActionResult:
    thought = await ctx.store.get("thoughts", params.thought_id)
    if thought is None:
        return ActionResult.error("Thought not found.", code="THOUGHT_NOT_FOUND")
    doc = await ctx.store.create("proposed_actions", {
        "thought_id": params.thought_id,
        "title": params.title,
        "rationale": params.rationale,
        "target_app": params.target_app,
        "target_tool": params.target_tool,
        "status": "pending",
        "created_at": now_iso(),
    })
    return ActionResult.success(
        summary=f"Proposed: {params.title}",
        data={"action_id": doc.id},
        refresh_panels=["thought_detail"],
    )


@chat.function(
    "list_proposed_actions",
    description="List Webbee's proposed next actions — from background analysis or live chat — optionally filtered by thought or status.",
    action_type="read",
    data_model=ProposedActionList,
)
async def list_proposed_actions(ctx, params: ListProposedActionsParams) -> ActionResult:
    where = {}
    if params.thought_id:
        where["thought_id"] = params.thought_id
    if params.status:
        where["status"] = params.status
    page = await ctx.store.query("proposed_actions", where=where or None, order_by="-created_at", limit=params.limit)
    items = [to_proposed_action(d) for d in page.data]
    return ActionResult.success(summary=f"{len(items)} proposed action(s).", data=ProposedActionList(items=items, total=len(items)))


@chat.function(
    "respond_to_action",
    description="Approve or dismiss one of Webbee's proposed actions. Approving does NOT execute it automatically — it just marks it accepted; the user (or Webbee in the same turn) then calls the real target tool.",
    action_type="write",
    effects=["proposed_action.update"],
)
async def respond_to_action(ctx, params: RespondToActionParams) -> ActionResult:
    action = await ctx.store.get("proposed_actions", params.action_id)
    if action is None:
        return ActionResult.error("Proposed action not found.", code="ACTION_NOT_FOUND")
    new_status = "approved" if params.decision == "approve" else "dismissed"
    await ctx.store.update("proposed_actions", params.action_id, {"status": new_status})
    return ActionResult.success(
        summary=f"Action {new_status}.",
        data={"action_id": params.action_id, "status": new_status},
        refresh_panels=["thought_detail"],
    )


# ──────────────────────────────────────────────────────────────────────────
# Sharing — self-contained, portable snapshot codes. See converters.py's
# comment for why: the platform has no cross-user store/context primitive
# reachable from normal user code, and a real @ext.webhook runs as
# "__webhook__", not "__system__" (verified directly against
# imperal_sdk/context.py's as_user() guard) — so a webhook-resolves-owner
# design would fail in production exactly like it does in tests. Packing
# the content into the code itself sidesteps the problem entirely: every
# step runs in perfectly ordinary, single-user context.
#
# Honest tradeoff, stated back to the user: this is a snapshot at the
# moment of sharing, not a live link — and once handed out, a code can't be
# revoked (there's no server-side gate to close). Anyone who has the code
# can decode it; don't share sensitive discussions this way.
# ──────────────────────────────────────────────────────────────────────────


@chat.function(
    "create_share_link",
    description="Create a share code for a Thought so another Imperal user can import a read-only snapshot of this discussion into their own My Thoughts. This is a snapshot at the moment of sharing (not a live link) and, once handed out, cannot be revoked — anyone with the code can decode it, so don't use this for sensitive discussions.",
    action_type="write",
    effects=["sharelink.create"],
)
async def create_share_link(ctx, params: CreateShareLinkParams) -> ActionResult:
    thought = await ctx.store.get("thoughts", params.thought_id)
    if thought is None:
        return ActionResult.error("Thought not found.", code="THOUGHT_NOT_FOUND")
    messages_page = await ctx.store.query(
        "thought_messages", where={"thought_id": params.thought_id}, order_by="created_at", limit=500,
    )
    messages = [
        {"role": m.data.get("role", "user"), "text": m.data.get("text", ""), "created_at": m.data.get("created_at", "")}
        for m in messages_page.data
    ]
    title = thought.data.get("title", "")
    code = encode_share_code(title, messages)
    label = title[:40] or params.thought_id
    await ctx.store.create("share_links", {
        "thought_id": params.thought_id,
        "label": label,
        "created_at": now_iso(),
    })
    return ActionResult.success(
        summary=(
            f"Share code ready for '{title}'. Send it to the other person — they run "
            "import_shared_thought with it. Snapshot only (not live), and can't be revoked once shared."
        ),
        data={"share_code": code},
        refresh_panels=["thought_detail"],
    )


@chat.function(
    "list_share_links",
    description="List the shares you've created (local record only — for your own reference, not an access-control list).",
    action_type="read",
    data_model=ShareLinkList,
)
async def list_share_links(ctx, params: ListShareLinksParams) -> ActionResult:
    where = {"thought_id": params.thought_id} if params.thought_id else None
    page = await ctx.store.query("share_links", where=where, order_by="-created_at", limit=50)
    items = [to_share_link(d) for d in page.data]
    return ActionResult.success(summary=f"{len(items)} share record(s).", data=ShareLinkList(items=items, total=len(items)))


@chat.function(
    "forget_share",
    description="Remove a share record from your own local list. Does NOT invalidate a code you already handed out -- there is no way to revoke a share code once shared (be honest with the user about this).",
    action_type="write",
    effects=["sharelink.delete"],
)
async def forget_share(ctx, params: ForgetShareParams) -> ActionResult:
    page = await ctx.store.query("share_links", where={"label": params.label}, limit=1)
    if not page.data:
        return ActionResult.error("Share record not found.", code="SHARELINK_NOT_FOUND")
    await ctx.store.delete("share_links", page.data[0].id)
    return ActionResult.success(summary="Removed from your local share list.", data={"label": params.label})


@chat.function(
    "import_shared_thought",
    description="Import a Thought another user shared with you — pass the full share_code they gave you. Creates your own independent copy you can keep discussing; it will not update if they keep talking in theirs.",
    action_type="write",
    effects=["thought.create"],
)
async def import_shared_thought(ctx, params: ImportSharedThoughtParams) -> ActionResult:
    snapshot = decode_share_code(params.share_code)
    if snapshot is None:
        return ActionResult.error("That doesn't look like a valid share code.", code="SHARECODE_MALFORMED")

    now = now_iso()
    src_title = snapshot.get("title", "")
    src_messages = snapshot.get("messages", [])
    new_thought = await ctx.store.create("thoughts", {
        "title": f"{src_title} (shared)",
        "status": "open",
        "message_count": len(src_messages),
        "project_id": "",
        "imported_from_code": True,
        "created_at": now,
        "last_activity_at": now,
    })
    for msg in src_messages:
        await ctx.store.create("thought_messages", {
            "thought_id": new_thought.id,
            "role": msg.get("role", "user"),
            "text": msg.get("text", ""),
            "created_at": msg.get("created_at", now),
        })

    return ActionResult.success(
        summary=f"Imported '{src_title}' as a new thought (snapshot — {len(src_messages)} messages) you can keep discussing.",
        data={"thought_id": new_thought.id},
        refresh_panels=["thoughts"],
    )


# ──────────────────────────────────────────────────────────────────────────
# Background analysis -- the actual point of this app. Runs daily across
# every user with open Thoughts (system context, per-user fan-out via
# ctx.store.list_users + ctx.as_user, the documented @ext.schedule pattern),
# looks at what's been discussed, and proactively drops a proposed action
# into the user's chat via ctx.deliver_chat_message -- Webbee speaking up
# without being asked, which is the whole promise of this app.
#
# Deliberately cheap and honest about what it is: a keyword heuristic
# (looks_actionable) decides WHETHER a thought is worth reasoning about at
# all, so we don't burn an LLM call on every open thought every night. Only
# thoughts that look actionable AND have had no proposal yet get a real
# ctx.ai.complete call to write the actual suggestion text.
# ──────────────────────────────────────────────────────────────────────────

_MIN_HOURS_BETWEEN_SCANS = 20  # avoid re-proposing on every run if cron fires more than daily


@ext.schedule("daily_thought_scan", cron="0 8 * * *")
async def daily_thought_scan(ctx) -> None:
    async for uid in ctx.store.list_users("thoughts"):
        user_ctx = ctx.as_user(uid)
        try:
            await _scan_one_user(user_ctx)
        except Exception as exc:  # noqa: BLE001 -- one user's failure must not stop the fan-out
            await ctx.log(f"daily_thought_scan failed for user {uid}: {exc}", level="warning")


async def _scan_one_user(user_ctx) -> None:
    page = await user_ctx.store.query("thoughts", where={"status": "open"}, limit=100)
    proposed_titles: list[str] = []

    for doc in page.data:
        thought_id = doc.id
        last_activity = doc.data.get("last_activity_at", "")
        if last_activity and hours_since(last_activity) < _MIN_HOURS_BETWEEN_SCANS:
            continue  # touched very recently -- let the live conversation breathe

        existing = await user_ctx.store.query(
            "proposed_actions", where={"thought_id": thought_id, "status": "pending"}, limit=1,
        )
        if existing.data:
            continue  # already has an unanswered suggestion -- don't pile on

        msgs_page = await user_ctx.store.query(
            "thought_messages", where={"thought_id": thought_id}, order_by="created_at", limit=50,
        )
        texts = [m.data.get("text", "") for m in msgs_page.data]
        if not texts or not looks_actionable(texts):
            continue

        transcript = "\n".join(f"- {t}" for t in texts[-20:])
        prompt = (
            "You are reviewing one of the user's ongoing idea discussions (a 'Thought') "
            "in the background, without being asked. Read the transcript below and decide "
            "if there is ONE concrete, specific next action worth proposing right now.\n\n"
            f"Thought title: {doc.data.get('title', '')}\n\nTranscript:\n{transcript}\n\n"
            "If there IS a good concrete next step, reply with exactly three lines:\n"
            "TITLE: <short action title>\nRATIONALE: <one or two sentences why, referencing the discussion>\n"
            "APP: <a plausible installed app/tool that could carry it out, or 'none'>\n"
            "If there is nothing concrete enough yet, reply with exactly: NONE"
        )
        try:
            result = await user_ctx.ai.complete(prompt=prompt, model="")
        except Exception:
            continue  # AI call failing must not break the whole nightly scan
        text = (result.text or "").strip()
        if text.upper().startswith("NONE") or "TITLE:" not in text:
            continue

        title, rationale, target_app = "", "", ""
        for line in text.splitlines():
            if line.upper().startswith("TITLE:"):
                title = line.split(":", 1)[1].strip()
            elif line.upper().startswith("RATIONALE:"):
                rationale = line.split(":", 1)[1].strip()
            elif line.upper().startswith("APP:"):
                target_app = line.split(":", 1)[1].strip()
        if not title:
            continue

        await user_ctx.store.create("proposed_actions", {
            "thought_id": thought_id,
            "title": title,
            "rationale": rationale,
            "target_app": "" if target_app.lower() == "none" else target_app,
            "target_tool": "",
            "status": "pending",
            "created_at": now_iso(),
        })
        proposed_titles.append(f"{doc.data.get('title', '')} → {title}")

    if proposed_titles:
        lines = "\n".join(f"🐝 **{t}**" for t in proposed_titles)
        try:
            # Best-effort -- the proposed_actions rows above are already
            # persisted, so a chat-injection failure (e.g. no kernel-injected
            # gateway context) must not look like the scan itself failed.
            await user_ctx.deliver_chat_message(
                f"While you were away I looked back over your open Thoughts and have "
                f"{len(proposed_titles)} idea(s) for what to do next:\n\n{lines}\n\n"
                f"Open **My Thoughts** to approve or dismiss them.",
                refresh_panels=["thoughts", "thought_detail"],
            )
        except Exception:
            pass


# ──────────────────────────────────────────────────────────────────────────
# Panels — ChatGPT-shaped: left = conversation list + always-visible
# Projects, center = the open thread (or an empty composer by default),
# right = reserved empty slot for future use (per explicit user decision).
# ──────────────────────────────────────────────────────────────────────────

_STATUS_COLOR = {"open": "blue", "archived": "gray", "pending": "yellow", "approved": "green", "dismissed": "gray"}


@ext.panel(
    "thoughts",
    slot="left",
    title="My Thoughts",
    icon="💭",
    default_width=300,
    min_width=240,
    max_width=460,
)
async def thoughts_panel(ctx, status: str = "open", **kwargs) -> object:
    thoughts_page = await ctx.store.query(
        "thoughts", where={"status": status} if status else None, order_by="-last_activity_at", limit=100,
    )
    projects_page = await ctx.store.query("projects", order_by="-created_at", limit=50)

    new_thought_button = ui.Button(
        "+ New thought", variant="primary", size="sm", full_width=True,
        on_click=ui.Call("__panel__thought_detail"),  # no thought_id -> empty composer
    )

    # Projects: always visible (per explicit decision), never collapsed away.
    project_items = [
        ui.ListItem(
            id=p.id,
            title=p.data.get("name", "(untitled project)"),
            subtitle=p.data.get("description", "")[:60],
            icon="📁",
            badge=ui.Badge(p.data.get("status", "active"), color="green" if p.data.get("status") == "active" else "gray"),
            on_click=ui.Call("__panel__thought_detail", thought_id=p.data.get("thought_id", "")),
        )
        for p in projects_page.data
    ]
    projects_section = ui.Section(
        title="📁 Projects",
        children=[
            ui.Button(
                "+ New project", variant="secondary", size="sm", full_width=True,
                on_click=ui.Call("quick_new_project"),
            ),
            ui.List(items=project_items) if project_items else ui.Text("No projects yet.", variant="caption"),
        ],
    )

    filter_row = ui.Select(
        options=[{"value": "open", "label": "Open"}, {"value": "archived", "label": "Archived"}, {"value": "", "label": "All"}],
        value=status,
        param_name="status",
        on_change=ui.Call("__panel__thoughts"),
    )

    if not thoughts_page.data:
        thoughts_section = ui.Section(title="💭 Thoughts", children=[
            filter_row,
            ui.Empty(message="No thoughts yet — start one above.", icon="💭"),
        ])
    else:
        grouped = group_thoughts_by_recency(thoughts_page.data)
        group_children = [filter_row]
        for label, docs in grouped:
            items = [
                ui.ListItem(
                    id=d.id,
                    title=d.data.get("title", "(untitled)"),
                    subtitle=f"{d.data.get('message_count', 0)} messages",
                    badge=ui.Badge(d.data.get("status", "open"), color=_STATUS_COLOR.get(d.data.get("status", "open"), "gray")),
                    on_click=ui.Call("__panel__thought_detail", thought_id=d.id),
                    actions=[
                        {"icon": "Edit2", "on_click": ui.Call("__panel__thought_detail", thought_id=d.id, renaming=True)},
                        {"icon": "Archive", "on_click": ui.Call("archive_thought", thought_id=d.id), "confirm": "Archive this thought?"},
                    ],
                )
                for d in docs
            ]
            group_children.append(ui.Section(title=label, children=[ui.List(items=items)]))
        thoughts_section = ui.Section(title="💭 Thoughts", children=group_children)

    root = ui.Stack(direction="v", gap=3, children=[
        new_thought_button,
        projects_section,
        ui.Divider(),
        thoughts_section,
    ])
    # Land on an empty "New thought" composer by default -- exactly like a
    # fresh chat client, per the explicit decision not to auto-open the
    # most recent thread. Fires once per discovery cycle.
    root.props["auto_action"] = ui.Call("__panel__thought_detail")
    return root


def _composer(thought_id: str) -> object:
    """Shared message-input row: same shape whether starting fresh or
    continuing an existing thought -- only the target function differs.

    Includes a voice-note attach control. STUB, stated honestly: this
    platform has no live microphone-capture UI primitive (verified against
    the real ui.* set -- ui.Audio is playback-only), so this is an
    already-recorded-file upload, not a record button, and it does not
    transcribe -- see attach_voice_note's docstring."""
    text_field = (
        ui.TextArea(
            placeholder="Reply...",
            rows=2,
            param_name="text",
            on_submit=ui.Call("add_thought_message", thought_id=thought_id, role="user"),
        )
        if thought_id
        else ui.TextArea(
            placeholder="Tell Webbee an idea...",
            rows=3,
            param_name="first_message",
            on_submit=ui.Call("start_thought"),
        )
    )
    voice_upload = ui.FileUpload(
        accept="audio/*",
        param_name="files",
        title="🎤 Attach voice note",
        hint="Upload an audio recording — not live dictation yet, and it isn't transcribed.",
        on_upload=ui.Call("attach_voice_note", thought_id=thought_id),
    )
    return ui.Stack(direction="v", gap=2, children=[text_field, voice_upload])


@ext.panel("thought_detail", slot="center", title="Thought", icon="💭", center_overlay=True)
async def thought_detail_panel(ctx, thought_id: str = "", show_share: bool = False, renaming: bool = False, **kwargs) -> object:
    # No thought_id -- this IS the default landing state (empty composer),
    # reached via auto_action below, exactly like a fresh "New chat".
    if not thought_id:
        return ui.Stack(direction="v", gap=4, children=[
            ui.Header(text="New thought", subtitle="Tell Webbee what's on your mind."),
            ui.Empty(message="Start typing below to begin a new discussion.", icon="💭"),
            _composer(""),
        ])

    thought = await ctx.store.get("thoughts", thought_id)
    if thought is None:
        return ui.Empty(message="This Thought no longer exists.", icon="⚠️")

    msgs_page = await ctx.store.query("thought_messages", where={"thought_id": thought_id}, order_by="created_at", limit=200)
    actions_page = await ctx.store.query("proposed_actions", where={"thought_id": thought_id, "status": "pending"}, limit=20)

    if renaming:
        header = ui.Stack(direction="v", gap=2, children=[
            ui.Input(
                placeholder="Thought title",
                value=thought.data.get("title", ""),
                param_name="title",
                on_submit=ui.Call("rename_thought", thought_id=thought_id),
            ),
            ui.Text("Press Enter to save.", variant="caption"),
        ])
    else:
        header = ui.Header(text=thought.data.get("title", "(untitled)"), subtitle=f"Status: {thought.data.get('status', 'open')}")

    header_actions = ui.Row(gap=2, children=[
        ui.Button("🔗 Share", variant="secondary", size="sm",
                  on_click=ui.Call("__panel__thought_detail", thought_id=thought_id, show_share=not show_share)),
        (ui.Button("📁 Turn into a Project", variant="primary", size="sm",
                   on_click=ui.Call("create_project_from_thought", thought_id=thought_id, name=thought.data.get("title", "")))
         if not thought.data.get("project_id") else ui.Badge("Project ✅", color="green")),
    ])

    # Inline share panel -- no modal (Dialog has no click trigger to open
    # it from), so the code is just revealed in-place on the same panel.
    share_block = None
    if show_share:
        share_block = ui.Card(
            title="Share this thought",
            content=ui.Stack(direction="v", gap=2, children=[
                ui.Text(
                    "This creates a one-time snapshot code -- not a live link. "
                    "Whoever imports it gets an independent copy; it won't update "
                    "as you keep talking here, and it can't be revoked once shared.",
                    variant="caption",
                ),
                ui.Button("Generate share code", variant="primary", size="sm",
                          on_click=ui.Call("create_share_link", thought_id=thought_id)),
            ]),
        )

    timeline_children = []
    for m in msgs_page.data:
        who = "🐝 Webbee" if m.data.get("role") == "webbee" else "You"
        timeline_children.append(ui.Text(f"**{who}:** {m.data.get('text', '')}", variant="body"))
    timeline = ui.Stack(direction="v", gap=2, children=timeline_children) if timeline_children else ui.Empty(message="No messages yet.", icon="💬")

    action_chips = []
    for a in actions_page.data:
        action_chips.append(ui.Card(
            title=f"🔔 {a.data.get('title', '')}",
            content=ui.Stack(direction="v", gap=2, children=[
                ui.Text(a.data.get("rationale", ""), variant="caption"),
                ui.Row(gap=2, children=[
                    ui.Button("Approve", variant="primary", size="sm",
                              on_click=ui.Call("respond_to_action", action_id=a.id, decision="approve")),
                    ui.Button("Dismiss", variant="secondary", size="sm",
                              on_click=ui.Call("respond_to_action", action_id=a.id, decision="dismiss")),
                ]),
            ]),
        ))

    body = [header, header_actions]
    if share_block:
        body.append(share_block)
    body.extend(action_chips)
    body.append(ui.Card(title="Discussion", content=timeline))
    body.append(_composer(thought_id))
    return ui.Stack(direction="v", gap=4, children=body)


@ext.panel("thought_context", slot="right", title="Context", icon="🧭", default_width=320)
async def thought_context_panel(ctx, **kwargs) -> object:
    """Reserved for future use -- deliberately empty for now."""
    return ui.Empty(message="Nothing here yet.", icon="🧭")
