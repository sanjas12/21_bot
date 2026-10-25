"""Build and check a portable Windows bundle for 21_bot using cx_Freeze."""

import json
import os
import platform
import shutil
import subprocess
import sys
import tomllib
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def build():
    if sys.argv[1:] not in (["build_exe"], ["build"]):
        raise SystemExit("Usage: python build.py build_exe")
    if sys.platform != "win32" or platform.machine().lower() not in ("amd64", "x86_64"):
        raise SystemExit("This build requires 64-bit Windows and 64-bit Python.")
    if sys.maxsize <= 2**32:
        raise SystemExit("Use 64-bit Python.")
    from cx_Freeze import Executable, setup

    os.chdir(ROOT)
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]
    version = project["version"]
    name = f"21_bot-{version}-windows-x64"
    output = ROOT / "build" / name
    if (
        (ROOT / "build").resolve() != ROOT / "build"
        or output.is_symlink()
        or output.resolve().parent != ROOT / "build"
    ):
        raise SystemExit("Unsafe build output path")
    if output.exists():
        shutil.rmtree(output)
    output.parent.mkdir(exist_ok=True)
    setup(
        name=project["name"],
        version=version,
        description="21_bot Telegram calendar",
        options={
            "build_exe": {
                "build_exe": str(output),
                "path": [str(ROOT / "src"), *sys.path],
                "packages": ["telebot", "dotenv", "tzdata", "sqlite3", "certifi"],
                "excludes": ["unittest", "tkinter"],
                "include_files": [
                    (str(ROOT / ".env.example"), ".env.example"),
                    (str(ROOT / "docs" / "CHANGELOG.md"), "docs/CHANGELOG.md"),
                    (str(ROOT / "docs" / "windows-build.md"), "README.md"),
                ],
                "include_msvcr": True,
                "optimize": 1,
            }
        },
        executables=[
            Executable(str(ROOT / "src" / "main.py"), target_name="21_bot.exe")
        ],
    )
    (output / "build-info.json").write_text(
        json.dumps({"name": "21_bot", "version": version}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    subprocess.run(
        [str(output / "21_bot.exe"), "--check"],
        cwd=output.parent,
        check=True,
        timeout=60,
    )
    archive = ROOT / "dist" / f"{name}.zip"
    archive.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for path in sorted(output.rglob("*")):
            if not path.is_file():
                continue
            relative = path.relative_to(output)
            if (
                path.name == ".env"
                or relative.parts[0] == "data"
                or path.suffix in (".sqlite3", ".sqlite", ".db")
            ):
                raise RuntimeError(
                    f"Private runtime data must not be bundled: {relative}"
                )
            bundle.write(path, Path(name) / relative)
    print(f"Portable application: {output}")
    print(f"Release archive: {archive}")


if __name__ == "__main__":
    build()
