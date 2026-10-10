"""US-6.4: every TODO/FIXME in the code must point to a GitLab issue (Bhatti p. 79)."""
import re
from pathlib import Path

SOURCE_DIR = Path(__file__).resolve().parent.parent / "src"
TRACKED_TODO = re.compile(r"#\s*(TODO|FIXME)\(#\d+\): \S")
ANY_TODO = re.compile(r"#\s*(TODO|FIXME)\b")


def test_no_untracked_todo_comments():
    untracked = [
        f"{path.relative_to(SOURCE_DIR)}:{line_number}: {line.strip()}"
        for path in SOURCE_DIR.rglob("*.py")
        for line_number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1)
        if ANY_TODO.search(line) and not TRACKED_TODO.search(line)
    ]
    assert untracked == [], "Link these comments to a GitLab issue: TODO(#123): ..."
