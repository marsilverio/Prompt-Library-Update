# GPT-MEMORY.md

## Current State, 2026-10-06

This file is the GPT / ChatGPT-specific companion to MEMORY.md.

Both memory systems remain relevant:
- MEMORY.md contains shared project truth and historical context.
- GPT-MEMORY.md contains GPT-specific working context, decisions, and handoff information.
- CLAUDE.md contains Claude-specific development guidance.
- GPT.md contains GPT-specific operating guidance.

## Prompt Forge

The Prompt Forge workbench redesign and stylesheet cache refresh from 2026-10-05 were reverted.

Reason: the new visual treatment was not preferred.

Current baseline:
- Use the pre-redesign Prompt Forge layout.
- The stylesheet cache reference is back to the pre-redesign value.
- Do not restore the reverted Forge workbench styling unless explicitly requested.

## Prompt Components

The current Prompt Components canvas has been substantially upgraded and should be treated as live functionality.

Important preserved capabilities include node resizing, marquee selection, alignment, live edge previews, explicit endpoints, endpoint reconnection, connection inspection, focus preservation, continuous dragging, canvas navigation, and improved graph compilation.

The SQLite database and graph persistence must remain intact.

## Account system

The account-management experiment has been reverted.

Do not reintroduce:
- account profiles
- authentication
- account switching
- account memory
- passwords
- account-specific licence state

unless explicitly requested.

## October 5 workspace work

A broader prompt-engineering suite was added and later consolidated by removing redundant evaluation/workflow workspaces.

The live specialised workspace IDs should always be verified against static/index.html before making assumptions.

Current known live IDs:
fill, audit, diff, cost, pulse, xray, splice, generate, example, adapter, simplify, tone, translate, gauntlet, batch.

## Working rule

When GPT changes the repository:
1. Inspect current state.
2. Identify the smallest affected surface.
3. Preserve unrelated recent changes.
4. Make the change.
5. Verify the resulting files or relevant diffs.
6. Update GPT-MEMORY.md.
7. Update MEMORY.md too when the change is shared project truth.
