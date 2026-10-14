"""Create reproducible source bundles from the public-file inventory."""
import argparse
import gzip
import io
import re
import tarfile
import zipfile
from public_files import ROOT, public_files


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--target", choices=("mac", "linux"), default="mac")
    parser.add_argument("--output", type=str)
    args = parser.parse_args()
    from pathlib import Path
    output_dir = Path(args.output) if args.output else ROOT / "dist"
    output_dir.mkdir(parents=True, exist_ok=True)
    files = public_files()
    for item in files:
        if item.is_symlink() or not item.is_file():
            raise RuntimeError("Missing public source file: " + item.relative_to(ROOT).as_posix())
    if args.target == "mac":
        output = output_dir / "coindex-1.9.0-source.zip"
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for item in files:
                relative = item.relative_to(ROOT).as_posix()
                info = zipfile.ZipInfo("coindex/" + relative, date_time=(2026, 10, 13, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = (0o100755 if item.suffix == ".sh" else 0o100644) << 16
                archive.writestr(info, item.read_bytes())
    else:
        version = re.search(r'^version\s*=\s*"([^"]+)"',
                            (ROOT / "pyproject.toml").read_text(), re.MULTILINE).group(1)
        output = output_dir / ("coindex-linux-" + version + "-source.tar.gz")
        with output.open("wb") as raw, gzip.GzipFile(fileobj=raw, mode="wb", mtime=0, filename="") as gz:
            with tarfile.open(fileobj=gz, mode="w") as archive:
                for item in files:
                    info = tarfile.TarInfo("coindex-linux/" + item.relative_to(ROOT).as_posix())
                    data = item.read_bytes()
                    info.size = len(data)
                    info.mode = 0o755 if item.suffix == ".sh" else 0o644
                    info.mtime = 1791849600
                    archive.addfile(info, io.BytesIO(data))
    print(output)


if __name__ == "__main__":
    main()
