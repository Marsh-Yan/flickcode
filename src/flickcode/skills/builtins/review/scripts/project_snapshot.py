import json
import os
import sys
from pathlib import Path

root = Path.cwd()
summary = {}
for directory, names, filenames in os.walk(root, followlinks=False):
    directory_path = Path(directory)
    names[:] = sorted(
        name for name in names
        if not (directory_path / name).is_symlink() and name not in {".git", ".venv", "node_modules"}
    )
    for filename in sorted(filenames):
        path = directory_path / filename
        if path.is_symlink():
            continue
        try:
            size = path.stat().st_size
        except OSError:
            continue
        extension = path.suffix.lower() or "[no extension]"
        bucket = summary.setdefault(extension, {"files": 0, "bytes": 0})
        bucket["files"] += 1
        bucket["bytes"] += size

output = json.dumps({"root": str(root), "extensions": dict(sorted(summary.items()))}, ensure_ascii=False)
json.dump({"success": True, "output": output, "error": None}, sys.stdout, ensure_ascii=False)
