# README media

These are captures of the actual coindex 1.9.0 UI using isolated, fictional demo data.

- `overview.png`: Agent-organized goal follow-up list.
- `conversations.png`: Unified local / SSH conversation tracking.
- `task-detail.png`: Goal, progress, next action and evidence.
- `connections.png`: Codex connection guide and fictional SSH sources.
- `workflow-demo.gif`: Eight-step playback of actual UI screenshots, with explanatory captions.

The GIF is a step-by-step interface demonstration. It does not depict a live model response, real SSH connection or successful message delivery. Analysis and nudging are disabled in the demo preview.

Screenshots contain only the application window. Source captures are excluded from Git, and the exported files contain no descriptive PNG metadata. Server labels and paths such as `dev-server` and `/workspace/example` are placeholders.

To reproduce, build the public application, run `python3 scripts/create-design-preview.py`, operate the isolated preview using `--demo`, and save reviewed window captures under `build/readme-captures/`. Then run `python3 scripts/create-readme-media.py` in a Python environment with Pillow. The original application content is cropped and resized, never regenerated.
