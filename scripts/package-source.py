"""Create a reproducible source bundle from an explicit public-file inventory."""
from pathlib import Path
import zipfile
from public_files import ROOT, public_files

root = ROOT
output = root/"dist/coindex-1.9.0-source.zip"
files = public_files()
output.parent.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
    for item in sorted(files):
        relative = item.relative_to(root).as_posix()
        if not item.is_file():
            raise RuntimeError("Missing public source file: " + relative)
        info = zipfile.ZipInfo("coindex/" + relative, date_time=(2026, 10, 13, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = (0o100755 if item.suffix == ".sh" else 0o100644) << 16
        archive.writestr(info, item.read_bytes())
print(output)
