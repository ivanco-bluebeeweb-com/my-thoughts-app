# My Thoughts

A Webbee-to-user discussion space — purely between you and Webbee, not a shared team notes app.

You bring an idea, discuss it over time in a thread (a **Thought**), and Webbee quietly
analyzes your open Thoughts once a day in the background (`@ext.schedule`) to propose
concrete next actions tied to real installed apps (Trello, Asana, WP Site Connector, etc.).
A Thought can graduate into a **Project**, and can be shared with another Imperal user as a
self-contained snapshot code.

## Core flow

1. `create_thought` — start a discussion with an optional first message.
2. `add_thought_message` — keep discussing; every message bumps `last_activity_at`.
3. Webbee's nightly scan (`daily_thought_scan` → `_scan_one_user`) reviews open, "stale enough"
   (touched >`_MIN_HOURS_BETWEEN_SCANS` ago), textually-actionable Thoughts and — via `ctx.ai.complete` —
   proposes at most one concrete next action per Thought, recorded as a `ProposedAction` (status
   `pending`). It never proposes twice while one is still pending on the same Thought.
4. `respond_to_action` — approve or dismiss. **Approving never auto-executes anything** — it just
   flips status to `approved`; the real tool call happens afterward, as an ordinary chat action.
5. `create_project_from_thought` — graduate a Thought into a `Project` once it's concrete enough
   to track as a deliverable.

## Sharing — the honest version

There is no live, cross-user data-sharing primitive reachable from ordinary extension code on
this platform: `ctx.store` is strictly single-user scoped, `ctx.as_user()`/`ctx.store.list_users()`
are `__system__`-context only (verified directly against `imperal_sdk/context.py`), and a real
`@ext.webhook` handler runs as `__webhook__`, not `__system__` — so a "webhook resolves the
owner" design fails in production exactly like it does in tests.

So sharing here means: `create_share_link` packs the Thought's title + messages **into the code
itself** (base64, versioned, no server round-trip) in the owner's own normal user context —
fully legal, no cross-user call anywhere. `import_shared_thought` decodes that code locally and
creates an independent copy in the importing user's own My Thoughts. This is a **snapshot at the
moment of sharing, not a live link**, and once a code is handed out it **cannot be revoked** —
anyone holding it can decode it. `forget_share` only removes your own local bookkeeping record of
having shared it; it does not invalidate the code. Don't share sensitive discussions this way.

## Testing

```bash
python3 -m pytest tests/ -v
```

22 tests cover the full flow end-to-end against `imperal_sdk.testing.MockContext`, including the
background scan (`_scan_one_user` — the per-user body extracted from the `@ext.schedule` fan-out,
per the SDK's documented testing pattern) and the share/import round trip.
