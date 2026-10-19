# Product improvements — 2026-10-17

Target: `D:\项目管理\video-parser`

## Scope
- Move default learning model/agent selection into Settings; let the user enable the desired local engines/models and retain the existing API-backed `llama.cpp` option. Keep learning and chat in the current UI.
- Allow a project/course title to be renamed and show its episode/part in Task Center.
- Make Task Center status/type filters and search quicker to scan.
- Show which episodes already have archived platform subtitles and avoid enqueuing duplicate subtitle downloads.

## Constraints
- Preserve all existing user changes; do not commit.
- Do not alter agent credentials or global agent configuration.
- Do not submit real course content or saved questions to any model while verifying these UI/data-management changes.

## Progress
- [x] Inspected the existing settings, local-agent catalog, project manifest/title data, task history, and subtitle archive/download flow. No project files changed remotely during inspection.
- [x] Add Settings-managed enabled model/engine list and default learning target; simplify the in-chat model label while retaining existing chat/conversation features.
- [x] Add safe project-title rename and propagate current title/episode labels into Task Center.
- [x] Add searchable, count-labelled Task Center filters.
- [x] Add a local subtitle-archive inventory and skip work for episodes already present.
- [x] Run focused offline tests, frontend type/build checks, review the rebuilt page and `git diff --check`; do not invoke real models.

## Implementation notes
- The existing local-agent inventory is metadata-only (`GET /ai/agents`); discovery is an explicit user action. The Settings UI should keep this boundary and never pass course data to discovery.
- Project title is mutable display metadata; its stable ID and archive path must remain unchanged.
- Subtitle availability should be determined from verified files already registered in the local library, not a remote/platform probe.

Status: implementation and focused verification are complete; local deployment and restart were subsequently completed at the user's request (see below). Existing user changes are preserved. No model call or commit was made.

## Verification — 2026-10-17
- 96 focused offline tests passed (73 main regressions + 23 transcription/subtitle checks).
- 12 new product browser regressions passed; existing local-agent and Settings browser scripts also passed against the final staged build.
- TypeScript checking, the Vite production build, rebuilt desktop/mobile page review, and `git diff --check` passed.
- Final fixes cover pending-video selection refresh, invalid mixed episode ranges, non-contiguous catalogue parts, recovery after clearing the selected task type, and narrow-screen model controls.
- Verification used an isolated build under `.local/product-improvements-resume-20261017-082817/final-dist`; it did not replace `frontend/dist` or restart the running workbench.
- See [completion and verification record](mcp-product-improvements-2026-10-17.md) for changes, evidence, reproduction and remaining validation boundaries.


## Local deployment — 2026-10-17
- At the user's explicit request, replaced `frontend/dist` with a fresh production build identical to the verified files and restarted the workbench via `start-web.ps1 -Port 15001 -OpenBrowser` in a separate native PowerShell window.
- Confirmed `http://127.0.0.1:15001` is healthy, serves the new index/assets, and passes read-only browser checks for the workspace, model Settings, Task Center, subtitles and 390px layout.
- All 32 existing task IDs/states were preserved; no active tasks were interrupted. No independent model service was stopped.
- Previous frontend and documents are backed up under `D:\项目管理\video-parser-backups\local-start-20261017-091413`; startup evidence is in `.local/local-start-20261017-091413/`.
