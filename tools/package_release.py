"""Build an installation archive from an explicit source allowlist."""

from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile

ROOT = Path(__file__).resolve().parents[1]


def build() -> Path:
    destination = ROOT / "dist" / "home-island-0.1.0.zip"
    destination.parent.mkdir(exist_ok=True)
    files = [ROOT / name for name in ("README.md", "LICENSE", "hacs.json")]
    for directory in ("custom_components/home_island", "docs", "examples"):
        files.extend(
            path
            for path in (ROOT / directory).rglob("*")
            if path.is_file() and path.suffix in {".py", ".json", ".yaml", ".md", ".png", ".svg"}
        )
    with ZipFile(destination, "w", compression=ZIP_DEFLATED) as archive:
        for path in sorted(files):
            archive.write(path, path.relative_to(ROOT).as_posix())
    return destination


if __name__ == "__main__":
    print(build())
