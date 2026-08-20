import unittest

from flickcode.teams.models import TeamMessage
from flickcode.teams.protocol import ApprovalRequest, ProtocolCodec


class TeamProtocolTests(unittest.TestCase):
    def test_unknown_protocol_is_not_authorizing(self):
        codec = ProtocolCodec()
        message = codec.encode(team_id="team", sender_id="member", kind="future.message", payload={"x": 1})
        self.assertFalse(codec.decode(message).known)

    def test_approval_requires_matching_request_and_digest(self):
        codec = ProtocolCodec()
        request = ApprovalRequest.create("member", "task", "run tests")
        approved = codec.encode(
            team_id="team",
            sender_id="lead",
            kind="approval.decision",
            payload={"request_id": request.request_id, "decision": "approve", "plan_digest": request.plan_digest},
        )
        self.assertTrue(codec.validate_approval(approved, request, lead_member_id="lead"))
        wrong = codec.encode(
            team_id="team",
            sender_id="lead",
            kind="approval.decision",
            payload={"request_id": request.request_id, "decision": "approve", "plan_digest": "wrong"},
        )
        self.assertFalse(codec.validate_approval(wrong, request, lead_member_id="lead"))


if __name__ == "__main__":
    unittest.main()
