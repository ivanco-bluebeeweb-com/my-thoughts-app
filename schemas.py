"""Pydantic params models + SDL entity contracts for My Thoughts.

All params models are module-scope (V17 federal invariant).
Entities/EntityLists follow the read-tool contract (V23): a single record
is an sdl.Entity subclass, a list result is sdl.EntityList[T] — never a
bare dict wrapper.
"""
from __future__ import annotations

from pydantic import BaseModel, Field
from imperal_sdk import sdl


# ──────────────────────────────────────────────────────────────────────────
# Domain entities
# ──────────────────────────────────────────────────────────────────────────


class Thought(sdl.Entity):
    """One idea/discussion thread — the core unit of My Thoughts."""
    title: str = ""
    status: str = ""  # open | archived
    message_count: int = 0
    project_id: str = ""  # set once graduated into a Project
    imported_from_code: bool = False  # true if this thread was created via import_shared_thought
    created_at: str = ""
    last_activity_at: str = ""


class ThoughtList(sdl.EntityList[Thought]):
    pass


class ThoughtMessage(sdl.Entity):
    """One message in a thought's discussion timeline."""
    title: str = ""  # satisfies sdl.Entity's required base field (unused here)
    thought_id: str = ""
    role: str = ""  # user | webbee
    text: str = ""
    created_at: str = ""


class ThoughtMessageList(sdl.EntityList[ThoughtMessage]):
    pass


class Project(sdl.Entity):
    """A thought that graduated into something actionable."""
    title: str = ""  # mirrors `name` below, satisfies sdl.Entity's required base field
    thought_id: str = ""
    name: str = ""
    description: str = ""
    status: str = ""  # active | done
    external_ref: str = ""  # free-text note, e.g. a Trello/Asana URL once created
    created_at: str = ""


class ProjectList(sdl.EntityList[Project]):
    pass


class ProposedAction(sdl.Entity):
    """One background-analysis suggestion tied to a thought."""
    thought_id: str = ""
    title: str = ""
    rationale: str = ""
    target_app: str = ""  # which installed app/tool this would call, e.g. "trello-connector"
    target_tool: str = ""  # e.g. "create_card"
    status: str = ""  # pending | approved | dismissed
    created_at: str = ""


class ProposedActionList(sdl.EntityList[ProposedAction]):
    pass


class ShareLink(sdl.Entity):
    """Local bookkeeping record of a share the owner created -- the actual
    share content travels self-contained in the code/url itself (see
    create_share_link), so this record is just "things I've shared", not
    an access-control gate (there is no live revoke for a code someone
    already has -- see create_share_link's docstring)."""
    title: str = ""  # satisfies sdl.Entity's required base field
    thought_id: str = ""
    label: str = ""  # short id used only to find this row again locally
    created_at: str = ""


class ShareLinkList(sdl.EntityList[ShareLink]):
    pass


# ──────────────────────────────────────────────────────────────────────────
# Params models
# ──────────────────────────────────────────────────────────────────────────


class CreateThoughtParams(BaseModel):
    title: str = Field(description="Short title for the idea/discussion (1 sentence max).")
    first_message: str = Field(
        default="",
        description=(
            "The FULL first message content, if the user already said something "
            "worth recording as the opening of the discussion. Write the actual "
            "text — never a placeholder."
        ),
    )


class AddThoughtMessageParams(BaseModel):
    thought_id: str = Field(description="Thought UUID. Obtain from list_thoughts — never invent.")
    role: str = Field(default="user", description="Who is speaking: 'user' or 'webbee'.")
    text: str = Field(description="The FULL message text — the actual content, never a placeholder.")


class ListThoughtsParams(BaseModel):
    status: str = Field(default="", description="Optional filter: 'open' or 'archived'. Empty = all.")
    limit: int = Field(default=50, description="Max thoughts to return.")


class GetThoughtParams(BaseModel):
    thought_id: str = Field(description="Thought UUID.")


class ArchiveThoughtParams(BaseModel):
    thought_id: str = Field(description="Thought UUID.")


class CreateProjectFromThoughtParams(BaseModel):
    thought_id: str = Field(description="Thought UUID to graduate into a project.")
    name: str = Field(description="Project name.")
    description: str = Field(default="", description="Optional project description.")


class ListProjectsParams(BaseModel):
    limit: int = Field(default=50, description="Max projects to return.")


class ListProposedActionsParams(BaseModel):
    thought_id: str = Field(default="", description="Optional: only actions for this thought.")
    status: str = Field(default="pending", description="Filter by status: pending | approved | dismissed | '' for all.")
    limit: int = Field(default=50, description="Max actions to return.")


class ProposeActionParams(BaseModel):
    """Used by Webbee (in chat, reasoning live) to record a suggestion tied
    to a thought — the same shape the background scan also writes, so both
    paths produce identical records."""
    thought_id: str = Field(description="Thought UUID this suggestion relates to.")
    title: str = Field(description="Short action title, e.g. 'Create a Trello board for this idea'.")
    rationale: str = Field(description="Why this action makes sense right now, in one or two sentences.")
    target_app: str = Field(default="", description="Which installed app this would call, if any, e.g. 'trello-connector'.")
    target_tool: str = Field(default="", description="Which tool on that app, e.g. 'create_board'.")


class RespondToActionParams(BaseModel):
    action_id: str = Field(description="ProposedAction UUID.")
    decision: str = Field(description="'approve' or 'dismiss'.")


class CreateShareLinkParams(BaseModel):
    thought_id: str = Field(description="Thought UUID to share.")


class ListShareLinksParams(BaseModel):
    thought_id: str = Field(default="", description="Optional: only links for this thought.")


class ForgetShareParams(BaseModel):
    label: str = Field(description="Label of the local share record to remove from your own list (does not invalidate a code someone already has -- see create_share_link).")


class ImportSharedThoughtParams(BaseModel):
    share_code: str = Field(description="The full share_code another user gave you (from their create_share_link result). Paste it exactly as received, unedited.")
