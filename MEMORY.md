# Prompt Library Pro — Memory

## Contacts

| Name | Role | Notes |
| :--- | :--- | :--- |
| Eugene Phillips | Solo developer & product owner | Building commercial Windows desktop app. Distribution via Payhip (not Gumroad). |

## Key Decisions

| Decision | Reasoning | Date |
| :--- | :--- | :--- |
| Chain Prompting reverted to detail panel tab | Standalone workspace was broken and over-engineered. Chain tab in right detail panel + Chain tab in prompt editor is simpler and fully functional. | 2026-05-17 |
| Standalone chain workspace removed | `#chainWorkspace` section, `chains` workspace switcher nav button, and all standalone chain JS functions deleted. Chain data still persists via `chain_ids` column in SQLite. | 2026-05-17 |
| **Correction (2026-09-19):** the row above is stale. `#chainWorkspace` exists live in `static/index.html` today (confirmed running, screenshotted, and redesigned this session — see History). It coexists with the separate detail-panel "Chain" tab described in Architecture below. Exact date/reason it was reinstated after 2026-05-17 is unknown; flagging rather than guessing. | Discovered while redesigning the workspace; line 167 of this file already said the nav for it was `✅ Live`, contradicting this row. | 2026-09-19 |
| Live variable preview added to detail panel | When filling variables in the detail panel, a live preview box shows the substituted prompt text in real time as the user types. | 2026-05-17 |
| Roles workspace kept as standalone | Roles workspace remains as a full-screen workspace switcher (sidebar nav button → takes over main area). | 2026-05-17 |
| Inno Setup for installer | Distribution pipeline: build.bat → build_installer.bat → single .exe via Inno Setup. ~50MB installer with Start Menu/Desktop shortcuts, Add/Remove Programs registration, optional DB cleanup on uninstall. | Prior |
| No cloud, no accounts | Fully local app. SQLite DB in user data directory. No internet required. | Prior |
| Onboarding tour — no video | Interactive spotlight tour only. Video-based onboarding was explicitly rejected. If onboarding is ever extended, do not add video. | 2026-06-04 |
| Build.bat Error 5 / Access Denied | Fixed: (1) `taskkill /F /IM PromptLibrary.exe /T >nul 2>&1` + 2s wait before clean step; (2) `--noupx` on pyinstaller command — UPX triggers Windows Defender mid-build. Both fixes live in Build.bat. | 2026-05-18 |

## Architecture

- **UI shell:** Three-pane layout — collapsible sidebar, prompt list/feed pane, right detail panel. Cool-slate theme (hue 255 OKLCH, teal accent hue 198), Inter font, Material Symbols icons. Light mode: bg 92.5% / surface 96.5% — correct depth hierarchy. Dark mode: bg 15% / surface 19%. Middle pane: dense list/feed with sort bar, group-by-folder mode, sticky section headers, hover-revealed action buttons.
- **Prompt editor:** Textarea with variable syntax highlighting, live preview, variable meta editor. Autosave on change.
- **Variable system:** `[[name]]`, `{{name}}`, `((name))` syntax. Types: text, number, date, dropdown. Filled via form in detail panel with live preview. `variable_meta[v].sort_order` controls display order. Keyboard: Ctrl+N, Ctrl+F, Ctrl+T, Ctrl+K.
- **Chain Prompting:** Lives in right detail panel as "Chain" tab and in prompt editor modal. Chain steps stored as `chain_ids` on each prompt. Phase-based runner with role badges, persona prepend, per-phase variable fill, live preview. Functions: `startChainRunner`, `renderChainRunner`, `PL_copyChainPhase`, `PL_showOutputCapture`, `PL_captureAndNext`, `PL_skipCapture`, `PL_finishChain`, `PL_exportFullChain`, `PL_stopChain`, `_updateChainPreview`.
- **Roles workspace:** Standalone full-screen workspace (sidebar nav → takes over main area). `roles` table in SQLite. State: `_rolesState`. Three copy formats: Structured, XML, Prose. Role dropdown in prompt editor wires `role_id` on save.
- **Chat Format:** `#pane-chat` in prompt editor. Copy turns with format selector (Plain text / ChatML / OpenAI JSON) via `PL_copyChatTurns()`. Premium-gated tab.
- **Premium tier:** SHA-256 key validation. Licence stored in SQLite `settings` table (not localStorage). `state.isPremium` set on startup via `/licence/check`. On Pro: all `premium-locked` classes removed from DOM. Gated (24 features): command palette, chain workspace nav, all advanced workspaces (Forge/Lab/Playground/Components/Meta/Optimizer/ToneCal/ContextBank/Gallery/Snippets/TextExpansion), version history, analytics, duplicate, Markdown/CSV/bulk export, chat format, rating & notes, Ctrl+T, theme toggle.
- **Data storage:** Local SQLite via Flask API. Single `.db` in user data directory.
- **Distribution:** `build.bat` (MD5 hash injection) → `build_installer.bat` → `.exe` via Inno Setup.

## History

- **V1:** Monolith. app.js ~88KB, index.html ~76KB. Unmaintainable.
- **V2:** Rebuilt from scratch. Modular architecture, size limits, phased approval gates, MD5 cache-busting.
- **Meta Prompting:** Removed. Do not rebuild or reference.
- **Chain Prompting:** Was briefly a standalone workspace — reverted 2026-05-17. Now lives in detail panel tab. **Correction (2026-09-19):** the standalone `#chainWorkspace` is back and live (see Key Decisions correction above) — redesigned this session from a dashed-box/accordion-card layout to a "signal rail" (hairline spine, `IN`/`01`/`02` mono tags). It now coexists with the detail-panel Chain tab as two separate features.
- **Scorecard workspace:** Removed 2026-06-02. Do not rebuild or reference.
- **Collection Builder workspace:** Removed 2026-06-02. Do not rebuild or reference.

## Current State (2026-06-24)

- **Payhip launch (2026-06-24):** App is now live on Payhip at https://payhip.com/b/WKSLO. Launch discount code `PlaygroundRelease` gives 50% off — first 5 uses only. A second discount code (25% off) is planned pending sales momentum. YouTube tutorial planned. Feature screenshots to be shared to Telegram community over coming days.

- **Build hash:** `89c28185` (app.js) / `bfd143ad` (app.css) — updated 2026-07-25. Run `python update_hash.py` after every app.js change.
- **Starter templates:** `/api/starter-templates` seeds 10 curated prompts on empty library
- **Variable ordering:** `variable_meta[v].sort_order` — up/down via `PL_moveVar(v, dir)`. Falls back to alphabetical.
- **Variable preview:** `#variablePreview` live preview + `#copyFilledBtn` in `#usePromptSection`
- **Roles workspace:** One-page scrollable editor. `buildRolePrompt()` fixed (strict mode). `prependRole()` outputs full structured role block (identity→KB).
- **Config panel:** Sidebar footer button → slides up. CSS: `config-panel-header`, `config-panel-body`, `config-provider-tab`.
- **Prompt starter select:** 168 deduplicated options.
- **App icon:** Multi-size ICO (16–256px) from `app-icon.png`. Both `icon.ico` and `static/icon.ico` updated.
- **Roles agent fields:** 6 DB columns (`audience`, `output_format`, `constraints`, `domain`, `tasks`, `response_style`) in `app.py` + `_role_payload` + `serialize_role`.
- **Text Expansion workspace (corrected 2026-06-22):** ⚠️ PLANNED — fully unbuilt. Prior entry claiming a `shortcuts.db` API exists in app.py was checked and is FALSE — no `shortcuts` table, no `shortcut` string anywhere in app.py. Backend AND UI both need building from scratch.
- **Context Bank workspace:** Live as of 2026-06-02. localStorage-backed reusable context blocks. Accessible via sidebar nav (`data-view="contextBank"`) and as slide-out panel in New Prompt modal (`#promptCtxPanel`). Full CRUD, category filter, search, insert-at-cursor.
- **Onboarding tour (fixed 2026-06-15):** 12-step spotlight tour. `initOnboarding()` now correctly called from BOOTSTRAP (was missing — tour never auto-launched). `promptlib.tourDone` localStorage key. Replay via sidebar footer "App tour" button (`#tourBtn`, onclick `PL_startOnboarding`). Old Components tutorial (`PL_startTutorial`, `#tutorialOverlay`) auto-launch disabled to prevent double-tour; still accessible if called directly. Tour step target IDs corrected: `#promptsContainer`, `#foldersList`, `#categoriesList`, `#workspacesToggle`. **Workspace previews (2026-06-15):** steps 6/7/9 now actually OPEN the workspace they describe (Agents→`openRolesWorkspace`, Power workspaces→`openForgeWorkspace`, Context Bank→`openContextBankWorkspace`) via a per-step `open` field + `_reconcileView()`. `_closeTourWorkspaces()` restores body scroll + nav state on library steps, finish, and Escape. Spotlight runs synchronously after `.open` (no rAF — throttles in background). Previews show for free users too (open-fns have no premium guard); nav buttons stay premium-locked outside the tour. **Preview polish (2026-06-15, hash 72411254):** workspace-preview steps (6/7/9) now set `target: null` and add `ob-preview` to `#onboardingOverlay`, whose CSS hides the dark `#onboardingSpotlight` so the real workspace shows fully (was: a pointless full-screen cutout that let the 70%-black dimmer sweep across the freshly-opened workspace). Step 8 ("The detail panel") now sets `openDetail: true` → `_openTourDetail()` opens the first library prompt's `#detailPanel` (was: spotlighted an empty/off-screen rail — the user saw nothing). Detail step keeps the dimmer + spotlight (panel is `z-index:20`, below the 9000 overlay; hole reveals it). Async/race-safe: `_openTourDetail()` returns `openDetail`'s promise, spotlight fires 380ms later (after the 0.32s slide) and only if `_step` is unchanged — else `_closeTourDetail()` removes the stray panel. `_closeTourDetail()` also runs on start/skip and on every workspace/library step. NOTE: the detail panel slide is transform-transition based and is *throttled/paused in headless preview* (Chromium) so it reads as `translateX(100%)` there; it runs normally in the visible WebView2 window — verify via DOM/`transition:none`, not headless screenshots. Verified end-to-end (DOM assertions): forward/back/Escape teardown clean, body scroll restored, one workspace open at a time, race handled.
- **Prompt Components workspace:** Live. Pre-expansion baseline (verified 2026-06-11): flat `BLOCKS` array (no `cat:` tags, no `CATEGORIES` array — uncategorised palette) + **23 `FRAMEWORKS`**: 5W2H, AIDA, APE, BAB, CARE, CO-STAR, COSTAR+, CSI+FBI, GROW, GRWC, META, OKR, PARA, PAS, PREP, RISEN, RODES, ROSES, RTF, SCQA, STAR, TRACE, ToT. `renderPalette()` targets `#pcwBlockGrid` / `#pcwFwList` (flat grid + list, no category pills/search). Drag-and-drop canvas, editable block cards, save to library. Sidebar nav (`data-view="components"`) + slide-out panel in New Prompt modal (`#promptComponentsPanel`, rendered separately by `_compPanelRender()`). Exposes `window._pcwBLOCKS` / `window._pcwFRAMEWORKS` globals (no `_pcwCATEGORIES` — not yet built). A 22-category/295-block/51-framework expansion (with new `#pcwCatPills`/`#pcwPaletteSearch`/`#pcwPaletteBody` palette UI) was built in `_rollbacks/app.js/app_20260611_110936.js` + `_rollbacks/index.html/index_20260611_110936.html` but never merged into live `static/` — reframed as planned future work, not yet scoped or scheduled.
- **Full-screen Prompt Viewer (fixed 2026-06-15):** `#promptViewer` overlay. `initPromptViewer()` now correctly called from BOOTSTRAP (was missing — close button and Escape key were broken). Opens via `window.PL_openViewer(id)`. Escape to close now works.
- **Prompt Optimizer workspace (corrected 2026-06-22):** ✅ LIVE, not planned — prior MEMORY.md entry was wrong. `#optimizerWorkspace` exists in index.html, `_optRunOptimize()` / `_optRunAnalyze()` in app.js call the shared `callAI()` helper. Pro-gated via `#optimizerNavBtn` (`premium-locked` + `data-premium="true"`).
- **Tone Calibrator workspace (built 2026-06-22):** ✅ LIVE. `#tonecalWorkspace`, mirrors Prompt Optimizer's structure. 6 tone presets (Formal/Casual/Persuasive/Concise/Friendly/Technical), calls shared `callAI()`, before/after panes, save-to-library. Pro-gated via `#tonecalNavBtn`. No new dependencies, no schema change.
- **Context Bank workspace (live):** `#contextBankWorkspace`. Left list panel + right editor. Category pills (Persona/Company/Audience/Product/Style/Other). `ctxSaveBtn`, `ctxCopyBtn`, `ctxDeleteBtn`. `_renderCtxList()` / `_openCtxEditor()`. Also available as side panel `#promptCtxPanel` in New Prompt modal.
- **Onboarding tour visual polish (2026-06-05):** Animated progress bar (`#obProgressBar`) fills as steps advance. Spotlight gets `ob-has-target` class → pulse animation when targeting an element. Card has accent glow border. `.ob-icon-wrap` has accent border and glow.
- **Cool-slate theme (2026-06-09):** Replaced warm-beige (hue 70) with cool-slate (hue 255) for both light and dark. Light: `--bg oklch(92.5% 0.007 255)`, `--surface oklch(96.5% 0.005 255)` — surface sits above bg, no depth inversion. Dark: `--bg oklch(15% 0.012 255)`. Accent is teal `oklch(40% 0.13 198)` light / `oklch(74% 0.13 198)` dark. CSS hash: `2083709d`.
- **Command palette redesign (2026-06-09):** Grouped sections (4 groups: Create/Navigate/Workspaces/Tools), 18 commands, icon tiles (`.cmd-ic`), subtitles (`.sub`), PRO chip in header (`.cmd-pro-chip`), keyboard hint footer. Now **Pro-gated** — free users see premium modal. `#cmdBtn` has `premium-locked` + `data-premium="true"`.
- **Pro-gating (confirmed 2026-06-15):** Internal `isPremium` guards on 8 open-functions. `#chainNavBtn` confirmed `premium-locked` + `data-premium="true"` in HTML (fixed 2026-06-15 — was missing). Chain tab in detail panel remains Free.
- **Dashboard workspace:** ⚠️ PLANNED — NOT IN LIVE FILES. `#dashboardWorkspace` has zero occurrences in `static/` files.
- **Template Gallery workspace:** ⚠️ PLANNED — NOT IN LIVE FILES. `#galleryWorkspace` has zero occurrences in `static/` files.
- **Snippets workspace (built 2026-06-22):** ✅ LIVE. `#snippetsWorkspace` — localStorage-backed (`pl_snippets`, mirrors Context Bank's `pl_ctx_blocks` pattern), categories Signatures/Disclaimers/Boilerplate/Greetings/Closings/Other, 6 starter snippets seeded on first open. Two surfaces: full CRUD workspace + `#promptSnippetsPanel` slide-out in the New Prompt modal (`#snipPanelToggleBtn`) for click-to-insert-at-cursor into `#promptContent` — inserts raw content with no wrapper text, unlike Context Bank's "--- Context: X ---" wrapping. Reuses `.ctx-*` CSS classes wholesale; only new CSS is the `#snippetsWorkspace` overlay rule. Pro-gated via `#snippetsNavBtn`. No new dependencies, no schema change.
- **Trash & Restore workspace:** ⚠️ PLANNED — NOT IN LIVE FILES. `#trashWorkspace` has zero occurrences in `static/` files.
- **Plan modal (fixed 2026-06-22):** Free column: 35 prompts, 8 folders, 5 tags & 8 categories per prompt, locked items listed. Pro column: 18 features accurately. Payhip CTA link live. Confirmed Pro stays one-off lifetime licence (not subscription).

## Current State (2026-07-25)

**Theme — correction.** The cool-slate (hue 255) entry below is WRONG. Live `static/app.css`
is warm beige + teal: `--bg oklch(93.5% 0.01 70)`, `--accent oklch(38% 0.14 190)`,
Fraunces display serif + Instrument Sans. Only two theme selectors exist:
`:root` (light) and `:root[data-theme="dark"]`. No `prefers-color-scheme` block.

**Snippets and Tone Calibrator workspaces were removed 2026-07-04** and replaced by the
7-workspace suite (Quick Fill, Auditor, Diff, Cost, Pulse, X-Ray, Splicer). The Snippets
*editor side panel* survives; only the standalone workspace died. Entries below still
listing them as live are stale.

### Library screen redesign (phase 1)
- Header cut from three stacked bars to two. Row 1: sidebar toggle, title block, search
  (the hero), `#cmdBtn`, `New prompt`. Row 2: `#filtersBtn` popover, sort, `#activeFilterPill`,
  and a right cluster (view toggle, group-by-folder, surprise-me). 180px -> 120px at desktop.
- `#filtersPop` holds Favourites + Rated. `#filtersCount` badge and the still-visible
  active pill keep filter state from hiding behind the popover. `window._syncFilterCount`
  is called from `refreshActivePill()`.
- `#viewTitle` was inheriting `--fs-2xl` (48px, the page-hero size); now `--fs-lg`.
  `#breadcrumb:empty { display: none }` — it reserved 20px on the library view.
- Cards: meta row muted to `--ink-4` and stripped of folder/clock glyphs (variable icon
  kept), chips capped at 2 cats + 2 tags with a `.card-tag.more` `+N`, category chips no
  longer borrow `--accent`. Bulk checkbox hover-reveals.
- Row 1 has `flex-wrap` plus a 1100px breakpoint dropping search to its own line —
  without it `#app`'s `overflow:hidden` clipped `New prompt`.

### Launcher (phase 2)
- `#launcherRecent` "Jump back in" strip, last 3 tools, localStorage `pl_ws_recent`,
  hidden while searching. Clicks are delegated and re-check `state.isPremium`.
- All 14 padlocks replaced by `.launcher-card-pro` gold chips.
- Group colour on icons only: build blue, refine purple, inspect orange, run green.
  This reclaimed `--accent`, which had been on all 17 card icons.
- `.launcher-grid > .launcher-card:first-child` is the lead card (34px icon).

### Batch Runner workspace (phase 3) — NEW, Pro
`#batchWorkspace`, `data-view="batch"`, icon `table_view`, in the launcher's Run group.
Runs one prompt across many input rows via `callAI`, sequentially.
- Three input modes: 1 variable = one value per line; 2+ variables = first line must be a
  CSV header naming them (`_brSplitCsv` handles quotes); no variables = each line is
  appended to the prompt as its input.
- `BR_MAX_ROWS` 50 (hard cap), `BR_WARN_ROWS` 25. Cost estimate reuses `COST_MODELS`.
- `_brCancel` flag checked between rows — `callAI` has no abort support and was NOT changed.
- A failed row does not halt the batch. Last template+rows persist to `pl_br_last`.
- Export CSV and Copy all go to the clipboard. Per-row Save posts to `/prompts`.

### Bugs fixed this session (all pre-existing)
- `.bulk-toolbar` set `display:flex`, which outranks the UA `[hidden]` rule — the toolbar
  held **49px of invisible dead space** above every prompt list at all times. Added
  `.bulk-toolbar[hidden] { display: none }`.
- Duplicate `#promptsContainer.list-view .card-actions` block set `opacity:1` after the
  hover rule, so the **card hover-reveal never worked**. Duplicates merged (Key Principle 14).
- Dark-theme `--c-blue` was authored at **hue 190** (teal's hue) while light uses 245, so
  the blue and teal **prompt colour labels were identical in dark mode**. Now hue 245.
- `Main.py` logging init had no try/except. A ReadOnly `error.log` crashed the app before
  launch. `_init_logging()` now falls back to the data dir, then to no file handler.

### Environment note (2026-07-25)
The whole working tree had the Windows **ReadOnly** attribute set — 1,910 files outside
`.git`, including `static/app.js`, `app.css`, `index.html`, `app.py`. This crashed the app
and would have blocked every edit. Also found: repo files dragged into a `New Folder/`,
an Explorer `desktop.ini`, and stale `app.js.tmp` / `index.html.tmp`. Cleared and cleaned.
Detect with: `Get-ChildItem -Force -File -Recurse | Where-Object { $_.Attributes -match 'ReadOnly' }`.

## Current State (2026-09-19)

- **Prompt Chain workspace redesign.** `#chainWorkspace` (the standalone step builder, see
  History correction above) redesigned from a dashed-box seed + circular-badge accordion
  cards to a "signal rail": one hairline spine runs through the seed and every step
  (`IN`, `01`, `02`... in mono type), no cards, shadows, or gradients. All functions/ids
  kept unchanged, only markup and CSS changed. Step markup classes renamed
  `chain-step`/`chain-step-num`/`chain-step-body` → `chainw-step`/`chainw-step-num`/
  `chainw-step-body` to fix a collision with an unrelated chain-search picker (see Gotchas
  in `CLAUDE.md`). Verified live via headless-browser screenshots in light and dark mode.
- **PR:** funben12/Prompt-Library-Update#8 (draft, being watched by this session).

## Feature Inventory — Free vs Pro

### Free (all users)
| Feature | Notes |
| :--- | :--- |
| Prompt library | Up to 35 prompts. Create, edit, delete, organise |
| Folders | Up to 8 folders |
| Tags & categories | Up to 5 tags & 8 categories per prompt |
| Variable system | `[[name]]` `{{name}}` `((name))` — text, number, date, dropdown |
| Variable live preview | Fill variables with live substitution preview |
| Chain prompting (detail panel) | Chain tab in right detail panel + prompt editor modal — NOT the nav workspace |
| Agents / Roles workspace | Full role builder — identity, voice, context, KB, skills |
| Copy formats (Structured / XML / Prose) | Role copy formats |
| Dashboard workspace | 🔲 Planned — not in static/ files |
| Trash & Restore workspace | 🔲 Planned — not in static/ files |
| Prompt starter (168 options) | Starter selector in prompt editor |
| Colour labels | Per-prompt colour coding |
| Favourites | Star/unstar prompts |
| Keyboard shortcuts | Ctrl+N, Ctrl+F, Ctrl+K |
| Import / Export (.plp pack) | Pack import/export |
| Starter templates | Auto-seeded on empty library |
| Dark theme | Fixed dark mode (cool-slate) |
| Onboarding tour | 13-step spotlight tour on first launch. Replay via "App tour" sidebar button. |

### Pro (licence required — SHA-256 key validation)
| Feature | Status | Notes |
| :--- | :--- | :--- |
| Unlimited prompts, folders, tags, categories | ✅ Live | Removes FREE_LIMITS caps |
| Command palette | ✅ Live | `#cmdBtn` + `Ctrl+K` — 18 commands, 4 groups. `premium-locked` |
| Prompt Chain workspace nav | ✅ Live | `#chainNavBtn` `premium-locked` — chain in detail panel stays Free |
| Playground workspace | ✅ Live | `#playgroundWorkspace` — run prompts live |
| Prompt Forge workspace | ✅ Live | `#forgeWorkspace` — structured prompt builder |
| Prompt Lab workspace | ✅ Live | `#labWorkspace` — A/B testing |
| Prompt Components workspace | ✅ Live | Flat block list + 23 frameworks (no categories yet). Drag-and-drop canvas |
| Metaprompting workspace | ✅ Live | `#metaWorkspace` — AI prompt rewriter |
| Prompt Optimizer workspace | ✅ Live | Pro-gated, calls shared `callAI()` helper. Corrected 2026-06-22 — was wrongly marked Planned |
| Tone Calibrator workspace | ✅ Live | Built 2026-06-22. Calls shared `callAI()`, mirrors Optimizer pattern |
| Context Bank workspace | ✅ Live | `#contextBankWorkspace` — left list + right editor, category pills |
| Template Gallery workspace | 🔲 Planned | Not in static/ files — described in prior sessions only |
| Snippets workspace | ✅ Live | Built 2026-06-22. localStorage-backed, mirrors Context Bank pattern + insert-at-cursor panel |
| Text Expansion workspace | 🔲 Planned | Fully unbuilt — no backend, no UI. Corrected 2026-06-22, prior `shortcuts.db` claim was false |
| Version history | ✅ Live | Per-prompt version log with restore |
| Analytics | ✅ Live | Usage stats, top prompts, tag clouds |
| Duplicate prompt | ✅ Live | One-click clone |
| Export — Markdown / CSV / Bulk | ✅ Live | Multiple export formats |
| Chat format tab | ✅ Live | Copy turns as Plain / ChatML / OpenAI JSON |
| Rating & notes | ✅ Live | Per-prompt star rating + private notes |
| Ctrl+T text case cycling | ✅ Live | Toggle case in prompt editor |
| Dark/light theme toggle | ✅ Live | User-switchable theme |
| In-app AI executor | ✅ Live | `callAI(systemPrompt, userMsg, maxTokens)` in app.js (~line 6997). Supports OpenAI, Anthropic, Gemini, OpenRouter. Corrected 2026-06-22 — was wrongly marked Planned |
| Version diff view | 🔲 Planned | Side-by-side diff between versions |

## Roadmap

### Pro — Planned
- **In-app AI executor (corrected 2026-06-22):** ✅ Already live, not planned. Shared `callAI()` helper in app.js, used by Prompt Optimizer, Metaprompting, Smart/AI tagging, Prompt Score, Roles AI persona generation. ⚠️ Key storage is plain `localStorage` (`pl_api_key_<provider>`), NOT DPAPI-encrypted as previously documented — this is a real gap if it matters for the security story, flagged but not yet fixed.
- **Version diff view:** Side-by-side diff between any two saved versions of a prompt. Complexity high — design TBD.
- **Text Expansion Layer 2 (system-wide):** Global keyboard hook via `pynput`/`keyboard`. Deferred — AV flag risk, requires explicit user opt-in. Do not build until Layer 1 is proven stable.

### Free — Planned
- **Bulk operations:** Checkbox-select multiple prompts → bulk tag, move, export, delete
- **Drag-and-drop folder assignment:** Drag prompt card onto folder in sidebar
- **Expanded keyboard shortcuts:** Additional shortcuts throughout app
- **Components panel drag-to-modal:** Drag blocks/frameworks from the modal side panel directly into the prompt textarea (approved 2026-06-02)
- **Interactive canvas (Components workspace):** Unlimited pan/zoom canvas, drag blocks to any position, moveable nodes, user-defined node connections (neural-link style). Approved direction 2026-06-02.

### Reference
- PRD exists covering full free/premium feature inventory, DB schema, API endpoints, licensing architecture, competitive positioning
---

## Current State (2026-10-06) — supersedes older state notes where they conflict

### Product architecture

Prompt Library Pro is currently a local-first Windows desktop prompt engineering application. The account-management experiment has been completely reverted. The product should again be treated as having no user accounts, no authentication, no account switching, no account memory, no password layer, and no account-specific licence state.

The SQLite database and Prompt Components graph core were deliberately preserved through the account-system reversion. Recent verification work focuses on database integrity and graph persistence rather than account functionality.

### Prompt Components canvas upgrade

The Prompt Components workspace has moved substantially beyond its earlier flat node editor baseline.

Current interaction work includes:

- Resizable component nodes, with stored resize state controlling rendered dimensions.
- Marquee selection and alignment controls.
- Improved selection and alignment feedback.
- Live edge previews while creating connections.
- Explicit connection endpoints.
- Endpoint reconnection.
- Connection inspector editing.
- Preservation of text-input focus while editing connection data.
- Continuous node dragging across canvas rerenders.
- Canvas navigation polish and restored node sizing.
- Improved graph prompt compilation for branches and convergence.

The strategic direction is a professional visual editor for prompt systems, with interaction depth approaching tools such as Figma, tldraw, or React Flow, while remaining purpose-built for prompt construction and graph compilation.

Do not replace this with a generic node editor, and do not damage the existing SQLite graph persistence while extending it.

### Nearby share (v0.2 of the Android companion, 2026-10-06)

- `share_server.py` runs a second, tiny Flask app on fixed port **47800** (started in its own thread from `Main.py` after `init_db()`; failure there is logged and never stops the main app). It only serves `GET /share/hello`, `POST /share/offer`, `GET /share/offer/<id>`. Private network addresses only, 256KB body cap, offers expire after 180s, 10 offers a minute per IP, 20 pending max. It has no route to `/api` or the database.
- Accepting is local only: `GET /api/share/inbox`, `POST /api/share/inbox/<id>` (`{accept}`), `POST /api/share/settings` (`{receiving, name}`) in `app.py`, all refused unless the request is loopback. Accepted prompts go into a `Received` folder (created on first use) with notes "Received from <device>".
- Settings keys (existing `settings` table, no schema change): `device_id` (uuid hex, created on first boot), `device_name` (defaults to hostname), `share_receiving` ('1' default on).
- `app.py` now has `_insert_prompt(conn, data)`; `create_prompt` and the share accept route both use it.
- UI: incoming offers show as AirDrop style cards top right (`.nearby-stack` / `.nearby-card`, polled every 3s, code in the main IIFE). The receive switch and computer name live in the "Continue on phone" modal under NEARBY SHARE.
- Scope gotcha: `static/app.js` has four top level IIFEs (main ends near line 28322). Later IIFEs (onboarding, viewer, phone share) cannot see `toast`, `escapeHtml` or `loadAll`; the main IIFE exposes `window.PL_toast`. The phone share panel's "Link copied" toast was silently broken by this until now.
- `grep -c "<script" static/index.html` is **4**, not 3 (CLAUDE.md triage note is stale).
- Desktop icon changed 2026-10-06 to the teal hardcover book with a prompt label (same art as the Android app): `icon.ico`, `static/icon.ico`, `app-icon.png`, plus `<link rel="icon">` in index.html. Old icons backed up in `_rollbacks/` as `icon v1.ico` and `static-icon v1.ico`; the old `app-icon.png` is in git history only (`*.png` is gitignored). The in-app logos `static/logo-mark.png` (sidebar) and `static/logo.png` now use the same book, and `mac/app-icon.icns` (referenced by `mac/setup.py`, previously missing) is generated from it.
- Sending (v0.3): each prompt card has a paper plane button (`window.PL_sendNearby(id)`) that opens "Send to nearby". `GET /api/share/devices` scans this computer's /24 on port 47800 (64 threads, 0.8s timeout, about 4s, excludes its own device ID); `POST /api/share/send {ip, prompt_id}` offers the prompt; `GET /api/share/send/<ip>/<offerId>` reports pending, accepted, declined or expired. Sending uses `urllib` only and refuses non-private addresses. Works to phones (app open) and to other desktops (laptop to laptop).
- Discovery fix (2026-10-07, after a real test where the phone found the laptop but not the reverse): the desktop now scans every private IPv4 /24 it has (route guess plus `gethostbyname_ex`, link local skipped, max 4 networks, 96 threads), always probes peers that recently said hello or sent an offer (`_peers`, kept 24h; phones send `?from=&name=&type=` on hello), bypasses the Windows system proxy for local calls, and the Send modal has "Add by address" (`GET /api/share/devices?ip=`) plus the scanned networks in its empty state. Root causes covered: wrong adapter picked (WSL, Hyper-V, VPN), system proxy, phone app not on screen.
- Root cause of desktop not finding phones (2026-10-07, confirmed in the 0.7.0 APK bytecode): `MainActivity.handleShare` matched `/share/hello` exactly, so the desktop probe `/share/hello?from=&name=&type=` got a 404. `share_server.probe()` now retries the plain path on a 404, so already installed phone builds are found. The phone source now strips the query string; rebuild the APK to pick it up. Backup: `_rollbacks/share_server v-pre-hello-fix.py`.
- Phone side lives in `funben12/AI-App-Factory` `apps/app-003-prompt-library-mobile` (v0.3: sends and receives; it only receives while the app is on screen).

### Memory maintenance rule

Substantial repository changes must update the relevant model-specific memory file automatically.

GPT changes update GPT-MEMORY.md. Claude changes update MEMORY.md and any applicable Claude-specific notes. When a change establishes shared project truth, MEMORY.md must also be updated.

Memory should describe the current resulting state and supersede stale instructions rather than accumulating contradictory history.

## Prompt Forge

The 2026-10-05 Prompt Forge workbench redesign and stylesheet cache refresh were reverted. The pre-redesign Prompt Forge layout is the current intended baseline. Do not reapply the reverted visual treatment unless explicitly requested.

### Prompt Forge frameworks and custom frameworks (2026-10-07)

- All framework definitions now live in `static/forge-frameworks.js` (`window.PL_FORGE_FRAMEWORKS`, 354 entries, each with `title` = the dropdown label). `app.js` builds `FORGE_FRAMEWORKS` from it (about 5,800 lines left app.js). The phone app ships a copy of the same file.
- Before this, 225 of the 354 dropdown options had no definition and silently did nothing. Every option now has fields; a Playwright check walks all 354 and confirms each renders and assembles.
- Loaded by its own `<script>` tag after components-data.js, so `grep -c "<script" static/index.html` is now 5. `mac/setup.py` lists the file.
- Custom frameworks: "+ New" beside the dropdown (or "+ New framework…" in it) opens an editor; typing an acronym makes one part per letter. Saved via `GET/POST /api/settings/forge-frameworks` into the settings key `forge_custom_frameworks` (JSON list, max 50, 12 parts each; no schema change). Shown first under "My frameworks" as keys `my_<id>`; Edit appears only for those. Same JSON shape as the phone's `forgeFrameworks`.
- Modal is built in JS, inserted before `#toastContainer`, z-index above the Forge workspace. `.btn` overrides `[hidden]`, so hidden buttons need an explicit `[hidden]{display:none}` rule.

### Workspace suite

A broader prompt engineering suite was added and wired into the existing launcher convention. Redundant evaluation/workflow workspaces were subsequently removed.

Current live specialised workspace IDs observed in static/index.html:

fill, audit, diff, cost, pulse, xray, splice, generate, example, adapter, simplify, tone, translate, gauntlet, batch.

Human-readable roles:

- Quick Fill
- Prompt Auditor
- Diff Lens
- Cost Lens
- Library Organizer
- Prompt X-Ray
- Prompt Splicer
- Prompt Generator
- Prompt from Example
- Model Adapter
- Prompt Simplifier
- Tone & Style Rewriter
- Prompt Translator
- Gauntlet Loop
- Batch Runner

The live files are authoritative. Older workspace descriptions in the historical changelog may describe experiments that were later removed.

### Recent stability and cleanup

October 5 work also included:

- app.py syntax repair after corruption around database initialisation.
- Removal of obsolete app - v1.py.
- Reversion of the account-management layer.
- Removal of account-lock styling and account-specific licence documentation.
- Database and graph smoke-test refocus.
- Fixes allowing remaining workspace dialogs to close.
- Workspace-suite refresh after workspace removal.
- Prompt Forge redesign and stylesheet cache refresh were reverted after review.
- Restoration of an existing premium licence key through the normal licence mechanism.

### Development direction

The current product priority is coherent prompt-engineering tooling rather than accumulating workspaces. New features should earn their place by providing a distinct job, should reuse existing launcher and workspace conventions, and should not create duplicate functionality.

Preserve the local-first architecture, SQLite data, graph persistence, existing licence system, and the established live-file workflow. Do not reintroduce the reverted account system unless explicitly requested.

### Gauntlet Loop prompt (2026-10-08)

The Gauntlet Loop workspace now generates the Gauntlet meta-prompt (goal, inspectable quality bar, Matt Shumer Claude of Duty style short agent prompt, builder and critic fan-out, blind A/B critique, live progress page, subagents and ultracode). Inputs are two textareas: Goal (required, `#gauntBuiltInput`) and References (optional, `#gauntRefsInput`). The old three-input AAA template and the language field were removed. Still client-side string templating, no AI call, no schema change. Backups: `_rollbacks/app v-pre-gauntlet-meta.js`, `_rollbacks/index v-pre-gauntlet-meta.html`.

### Variable types expansion (2026-10-08)

- Desktop fill sheet gained 8 types: Segmented, Stepper, Percentage, Date Range, Today, Title Case, Hashtags, List. Total is now 44. No schema change, `variable_meta` stays freeform JSON.
- Output formatting per type happens in `_readVarControlValue` via `_PL_formatVar` (title case, `#` hashtags, `- ` bullets, `%`, `a to b` dates). The input keeps the raw value, the preview and copy use the formatted one.
- Mobile companion (AI-App-Factory `apps/app-003-prompt-library-mobile`) now keeps `variable_meta` on import as `varMeta` and renders the right control per type through a new `vartypes.js`, with the same 8 new types. Types are set on desktop only, nearby share does not carry them yet (needs `MainActivity.java` offer JSON and `share_server.py` changes).
- Backups: `_rollbacks/app v-pre-var-types-2.js` and `.css`. Cache hashes refreshed with `update_hash.py`.
- Stage 2 (2026-10-08): per-variable `wrap` key in `variable_meta` (quotes, codefence, xml tag named after the variable), set in the variable editor row, applied in `_readVarControlValue`. New types Clipboard (paste button) and Library Prompt (inserts another prompt's content), 46 types total. `replaceVariables` is now single pass so inserted text is never re-expanded and `$` in values is safe. Backups: `_rollbacks/app v-pre-var-types-3.js` and `.css`.
- Mobile stage 2: editor has a Variable types section (type picker, options, wrap), plus Clipboard and Library prompt types. Phone saves `varMeta` with `wrap`.
- Nearby share now carries `variable_meta` both ways (2026-10-08). Desktop: `share_server._meta()` cleans incoming settings (50 vars, size caps, known keys only), `app.py` `/api/share/send` includes it, accept saves it through the normal prompt insert. Phone: `MainActivity.cleanVarMeta` on receive, `varMeta` sent as `variable_meta`. Backups: `_rollbacks/share_server v-pre-nearby-types.py`, `_rollbacks/app v-pre-nearby-types.py`. Phone Java change needs the APK rebuilt and reinstalled to take effect.
- Mobile parity (2026-10-08): the phone now renders every desktop variable type (added Range, Range Slider, Ranked List, Matrix, Emoji, Icon names, Duration, Timezone, Language) and its editor sets type, options, default, wrap, Show when filling and multi. Prompts can be written, typed and filled entirely on the phone. Icon Picker on the phone shows icon names as chips (no Material Symbols font on the phone). Paragraph `size` is not carried to the phone.
- Open: desktop live preview chains sequential replaces, copy output is correct.
