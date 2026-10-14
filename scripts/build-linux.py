#!/usr/bin/env python3
"""Build a Linux wheel and an explicit public-source archive."""
import argparse
import hashlib
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=pathlib.Path, default=ROOT / "dist/Linux")
    args = parser.parse_args()
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=True)
    subprocess.run([sys.executable, "-m", "pip", "wheel", "--no-deps",
                    "--no-build-isolation", "--wheel-dir", str(output), str(ROOT)], check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/package-source.py"),
                    "--target", "linux", "--output", str(output)], check=True)
    subprocess.run([sys.executable, str(ROOT / "scripts/check-public-release.py"),
                    "--target", "linux", "--artifacts", str(output)], check=True)
    products = sorted([*output.glob("coindex_linux-*.whl"),
                       *output.glob("coindex-linux-*-source.tar.gz")])
    lines = [hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name
             for path in products]
    (output / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    for path in products:
        print(path)
    print(output / "SHA256SUMS.txt")


if __name__ == "__main__":
    main()
