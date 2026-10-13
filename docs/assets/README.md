# README media

The static screenshots show the actual coindex 1.9.0 UI using isolated, fictional data.
The product story combines those screenshots, workflow motion graphics and native UI
captures from a temporary build that simulates nudge state changes.

- `overview.png`: Agent-organized goal follow-up list.
- `conversations.png`: Unified local / SSH conversation tracking.
- `task-detail.png`: Goal, progress, next action and evidence.
- `connections.png`: Codex connection guide and fictional SSH sources.
- `workflow-poster.png`: Three machine sources become goal / progress / next-action entries.
- `workflow-demo.gif`: 46-second product story, from forgotten work to follow-up and nudging.
- `nudge-demo.gif`: Dedicated 15-second one-click nudge sequence.
- `nudge-story.png`: Native nudge UI and the contextual reminder shown together.

No model call, SSH connection or real message was sent to produce this media. The
simulated receipt is visibly labeled `演示回执`, and the illustrated Agent reply is
labeled `虚构回复`. Every film frame carries `虚构演示数据 · 催办流程示意`.
The shipped application's ordinary `--demo` mode keeps analysis and nudging disabled.

Screenshots contain only the application window. Source captures are excluded from Git, and the exported files contain no descriptive PNG metadata. Server labels and paths such as `dev-server` and `/workspace/example` are placeholders.

The MP4 is a 1920 × 1080, 30 fps version of the same 46-second timeline, with a
procedurally composed original 120 BPM electronic score. Chapter changes, goal
entries, the nudge click and demo receipt are aligned to its half-second beat grid.
It is hosted as an additional 1.9.0
Release asset; it does not replace the application or source release packages.

See [product-film.md](../product-film.md) for the storyboard, safety boundaries and
reproduction instructions. Native captures are cropped and resized; the renderer
does not regenerate application pixels or draw a fictional coindex interface.
