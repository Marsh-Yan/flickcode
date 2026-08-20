from __future__ import annotations

import json
import unittest

from flickcode.subagents.models import AgentToolResponse
from flickcode.subagents.tool import AgentTool


class _Coordinator:
    def __init__(self):
        self.requests = []

    def handle(self, request):
        self.requests.append(request)
        return AgentToolResponse(True, task_id=request.task_id or "agent-000000000001", status="running", background=True)


class AgentToolTests(unittest.TestCase):
    def setUp(self):
        self.tool = AgentTool()
        self.coordinator = _Coordinator()
        self.tool.bind(self.coordinator)

    def test_schema_is_stable_and_does_not_enumerate_roles(self):
        schema = self.tool.spec.input_schema
        self.assertEqual(set(schema["properties"]), {"operation", "type", "task", "role", "background", "task_id"})
        self.assertNotIn("enum", schema["properties"]["role"])

    def test_defined_start_and_query_use_one_tool(self):
        result = self.tool.execute({"operation": "start", "type": "defined", "task": "work", "role": "explore", "background": True})
        self.assertTrue(result.success)
        self.assertEqual(json.loads(result.output)["task_id"], "agent-000000000001")
        self.assertEqual(self.coordinator.requests[0].role, "explore")
        query = self.tool.execute({"operation": "status", "task_id": "agent-000000000001"})
        self.assertTrue(query.success)

    def test_unknown_or_missing_operation_is_rejected(self):
        self.assertFalse(self.tool.execute({}).success)
        self.assertFalse(self.tool.execute({"operation": "explode"}).success)


if __name__ == "__main__":
    unittest.main()
