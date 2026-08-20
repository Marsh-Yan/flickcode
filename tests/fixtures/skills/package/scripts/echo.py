import json
import sys

payload = json.load(sys.stdin)
json.dump({"success": True, "output": payload["value"], "error": None}, sys.stdout)
