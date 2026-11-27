#!/usr/bin/env -S uv run python
"""Fail if committed Postman JSON differs from a fresh generate.

ISO dates in the env (date_of_service) are normalized so daily regenerate
does not false-fail; everything else is a byte compare.

Fix: ./scripts/generate_postman_collection.py && git add postman/Prior_Auth_API*.json
"""

from __future__ import annotations

import difflib
import re
import shutil
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POSTMAN = ROOT / "postman"
FILES = (
    "Prior_Auth_API.postman_collection.json",
    "Prior_Auth_API.postman_environment.json",
)

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _normalize(text: str) -> str:
    return _ISO_DATE.sub("<date>", text)


def main() -> int:
    for name in FILES:
        path = POSTMAN / name
        if not path.is_file():
            print(f"missing {path} — run ./scripts/generate_postman_collection.py and commit")
            return 1

    from scripts import generate_postman_collection as gen

    tmp = Path(tempfile.mkdtemp(prefix="postman-check-"))
    try:
        old_out = gen.OUT
        gen.OUT = tmp
        try:
            gen.main()
        finally:
            gen.OUT = old_out

        drifted = False
        for name in FILES:
            committed = (POSTMAN / name).read_text()
            generated = (tmp / name).read_text()
            if _normalize(committed) == _normalize(generated):
                continue
            drifted = True
            print(f"diff: postman/{name}")
            diff = difflib.unified_diff(
                committed.splitlines(keepends=True),
                generated.splitlines(keepends=True),
                fromfile=f"postman/{name} (committed)",
                tofile=f"postman/{name} (generated)",
                n=2,
            )
            sys.stdout.writelines(list(diff)[:80])
            print()

        if drifted:
            print("Postman artifacts out of date.")
            print(
                "Fix: ./scripts/generate_postman_collection.py && git add postman/Prior_Auth_API*.json"
            )
            return 1

        print(f"postman check ok ({', '.join(FILES)})")
        return 0
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
