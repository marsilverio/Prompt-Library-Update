# GPT.md

## Purpose

This file is the GPT / ChatGPT specific companion to CLAUDE.md.

The repository also contains:
- CLAUDE.md, shared development guidance plus Claude-specific operating context
- MEMORY.md, shared project memory
- GPT.md, GPT / ChatGPT-specific operating guidance
- GPT-MEMORY.md, GPT / ChatGPT-specific working memory

All four files are relevant. Do not treat GPT files as replacements for the Claude files.

## GPT / ChatGPT operating context

When working on Prompt Library Pro:

1. Treat the live repository files as authoritative over stale changelog entries.
2. Preserve the local-first Windows architecture, SQLite database, existing licence system, and Prompt Components graph persistence.
3. Prefer surgical changes over rewrites or parallel systems.
4. Before changing an existing feature, inspect its current implementation and recent Git history.
5. Preserve unrelated work when reverting or modifying a specific feature.
6. Do not reintroduce the reverted account-management system unless explicitly requested.
7. Do not invent workspace IDs, features, or architecture. Verify them in the live files.
8. When a requested change is ambiguous, make the smallest reversible interpretation that satisfies the request.
9. When a substantial change is made, update GPT-MEMORY.md and, where the information is shared project truth, update MEMORY.md as well.
10. Keep Claude-specific and GPT-specific notes clearly separated. Shared product facts belong in MEMORY.md.

## Memory update requirement

After every substantial repository change, GPT must update GPT-MEMORY.md in the same change sequence.

A change is substantial when it changes functionality, architecture, UX, workspace behaviour, persistence, licensing, project direction, important bugs, or another decision that would materially affect future development.

For shared project facts, also update MEMORY.md. Do not wait for a separate request.

The memory update must describe the resulting state, not merely the intention. Keep it concise and remove or supersede stale guidance when necessary.

## Current Prompt Forge baseline

The Prompt Forge workbench redesign from 2026-10-05 was reverted. The pre-redesign layout is the current baseline.

Do not reapply the reverted workbench CSS or stylesheet cache version unless explicitly requested.

## Current Prompt Components direction

Prompt Components is a professional visual prompt-system editor, not a generic node editor.

Preserve its current interaction depth, including:
- node resizing
- marquee selection
- alignment controls
- live edge previews
- explicit connection endpoints
- endpoint reconnection
- connection inspector editing
- text-input focus preservation
- continuous dragging across rerenders
- canvas navigation
- branch and convergence prompt compilation

Do not damage SQLite graph persistence while extending it.

## Model-specific responsibility

GPT should maintain GPT.md and GPT-MEMORY.md when GPT-specific decisions, working assumptions, or implementation history materially change.

Claude should continue maintaining CLAUDE.md and MEMORY.md according to the existing project workflow.

If a fact affects the whole project, record it in MEMORY.md as well as the appropriate model-specific memory file.
