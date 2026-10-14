"""Build installed resources from the single public upstream asset tree."""
from pathlib import Path
import ast
import re
import shutil
import subprocess
import sys

from setuptools import find_packages, setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent
ASSETS = (
    "Brand/AppIcon.png",
    "CustomPets/coindex-cat/pet.json",
    "CustomPets/coindex-cat/spritesheet.png",
)


class BuildPublicResources(build_py):
    def run(self):
        super().run()
        target = Path(self.build_lib) / "coindex_linux" / "resources"
        for name in ASSETS:
            output = target / name
            output.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(ROOT / "Resources" / name, output)
        shutil.copyfile(ROOT / "LICENSE", target / "LICENSE")
        subprocess.run([sys.executable, str(ROOT / "scripts/create-demo.py"),
                        str(target / "demo.json")], check=True)

    def get_outputs(self, include_bytecode=1):
        target = Path(self.build_lib) / "coindex_linux" / "resources"
        return super().get_outputs(include_bytecode) + [
            str(target / name) for name in (*ASSETS, "LICENSE", "demo.json")
        ]


# Explicit setup arguments keep source builds working with Ubuntu's older
# setuptools when --no-build-isolation is selected. pyproject remains canonical.
PROJECT = (ROOT / "pyproject.toml").read_text(encoding="utf-8")


def field(name):
    return ast.literal_eval(re.search(r"^" + re.escape(name) + r"\s*=\s*(.+)$",
                                     PROJECT, re.MULTILINE).group(1))


setup(
    name=field("name"),
    version=field("version"),
    description=field("description"),
    url=field("Homepage"),
    project_urls={"Upstream": field("Upstream")},
    long_description=(ROOT / "README.md").read_text(encoding="utf-8"),
    long_description_content_type="text/markdown",
    python_requires=field("requires-python"),
    license="MIT",
    packages=find_packages(include=("coindex_linux", "backend")),
    include_package_data=True,
    install_requires=field("dependencies"),
    classifiers=field("classifiers"),
    entry_points={"console_scripts": ["coindex-linux=coindex_linux.app:main"]},
    cmdclass={"build_py": BuildPublicResources},
)
