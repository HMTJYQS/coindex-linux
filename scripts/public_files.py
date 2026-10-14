"""Single allowlist for public source packaging and privacy checks."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def public_files():
    files = [ROOT/name for name in ("README.md", "DESIGN.md", "LICENSE", ".gitignore",
                                   "CONTRIBUTING.md", "SECURITY.md", "CHANGELOG.md",
                                   "pyproject.toml", "setup.py", "MANIFEST.in", "UPSTREAM.md")]
    for folder in ("Sources", "backend", "coindex_linux", "scripts", "tests", "design/reference", "docs", ".github"):
        files += [p for p in (ROOT/folder).rglob("*") if p.is_file() and "__pycache__" not in p.parts
                  and (p.suffix in (".swift", ".py", ".sh", ".md", ".json", ".LICENSE", ".yml", ".yaml")
                       or p.name == "LICENSE") and p.name != "auth.json"]
    files += [ROOT/"Resources/CustomPets/coindex-cat"/name for name in
              ("pet.json", "spritesheet.png", "generation.json", "generation-prompt.md", "source-atlas.png")]
    files += [ROOT/"Resources/Brand/AppIcon.png"]
    files += [ROOT/"docs/assets"/name for name in
              ("overview.png", "task-detail.png", "conversations.png", "connections.png", "workflow-demo.gif",
               "workflow-poster.png", "nudge-demo.gif", "nudge-story.png", "linux-overview.png")]
    return sorted(set(files))
