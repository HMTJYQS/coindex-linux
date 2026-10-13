"""Check public source and app contents without printing potentially secret values."""
import ipaddress
import json
import re
from public_files import ROOT, public_files

TOKENS = re.compile(rb"(?:gh[pousr]_[A-Za-z0-9]{30,}|github_pat_[A-Za-z0-9_]{40,}|sk-[A-Za-z0-9_-]{30,}|AKIA[A-Z0-9]{16})")
USER_PATH = re.compile(rb"/(?:Users|home)/[^\s\"'<>/]+")
IP = re.compile(rb"\b(?:\d{1,3}\.){3}\d{1,3}\b")
FORBIDDEN_NAMES = {"auth.json", "config.toml", "pet-preferences.json", ".DS_Store"}
FORBIDDEN_SUFFIXES = {".sqlite", ".wal", ".log", ".pem", ".key", ".pyc"}
ALLOWED_NETWORKS = [ipaddress.ip_network(x) for x in ("127.0.0.0/8", "192.0.2.0/24", "198.51.100.0/24", "203.0.113.0/24")]
issues = []


def issue(path, category):
    issues.append({"file": str(path.relative_to(ROOT)), "category": category})


def check(path):
    if path.is_symlink() or not path.is_file():
        issue(path, "missing file or symlink")
        return
    if path.name in FORBIDDEN_NAMES or path.suffix in FORBIDDEN_SUFFIXES:
        issue(path, "private file type")
    data = path.read_bytes()
    if TOKENS.search(data):
        issue(path, "credential-like value")
    if USER_PATH.search(data):
        issue(path, "absolute personal home path")
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        offset = 8
        while offset + 12 <= len(data):
            length = int.from_bytes(data[offset:offset+4], "big")
            kind = data[offset+4:offset+8]
            if kind in (b"eXIf", b"tEXt", b"zTXt", b"iTXt", b"caBX"):
                issue(path, "image metadata requiring review")
            offset += length + 12
    elif path.suffix in (".py", ".swift", ".sh", ".md", ".json", ".yml"):
        for match in IP.findall(data):
            try:
                address = ipaddress.ip_address(match.decode())
            except ValueError:
                continue
            if not any(address in network for network in ALLOWED_NETWORKS):
                issue(path, "non-example network address")


source = public_files()
for path in source:
    check(path)
app = ROOT/"dist/coindex.app"
if not app.is_dir():
    issue(app, "public app has not been built")
else:
    for path in app.rglob("*"):
        if path.is_file() or path.is_symlink():
            check(path)
    resources = app/"Contents/Resources"
    if (resources/"Pets").exists():
        issue(resources/"Pets", "imported Codex artwork in public app")
print(json.dumps({"public_source_files": len(source), "issues": issues}, indent=2))
raise SystemExit(bool(issues))
