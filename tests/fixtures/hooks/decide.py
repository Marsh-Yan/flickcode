"""Controlled Hook decision fixture used by integration tests."""

from __future__ import annotations

import json
import sys


decision = sys.argv[1] if len(sys.argv) > 1 else "allow"
if decision == "deny":
    print(json.dumps({"decision": "deny", "reason": "fixture policy"}))
elif decision == "invalid":
    print("not-json")
elif decision == "fail":
    raise SystemExit(3)
else:
    print(json.dumps({"decision": "allow"}))
