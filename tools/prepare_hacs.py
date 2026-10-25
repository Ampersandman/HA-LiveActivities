"""Set publishing metadata after the owner chooses a real GitHub repository.

This edits local metadata only; it does not create or publish a repository.
"""

import argparse
import json
import re
from pathlib import Path


def prepare(repository: str, maintainer: str, manifest_path: Path) -> None:
    repository = repository.rstrip("/").removesuffix(".git")
    if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
        raise ValueError("Use a real https://github.com/OWNER/REPOSITORY URL")
    maintainer = maintainer.removeprefix("@")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}", maintainer):
        raise ValueError("Use the maintainer's GitHub username")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.update(
        documentation=repository, issue_tracker=repository + "/issues", codeowners=["@" + maintainer]
    )
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repository", required=True)
    parser.add_argument("--maintainer", required=True)
    args = parser.parse_args()
    prepare(
        args.repository,
        args.maintainer,
        Path(__file__).resolve().parents[1] / "custom_components/home_island/manifest.json",
    )
