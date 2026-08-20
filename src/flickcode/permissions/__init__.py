"""Permission system — five-layer access control for FlickCode."""

from flickcode.permissions.engine import PermissionEngine
from flickcode.permissions.models import CheckResult, PermissionMode

__all__ = [
    "CheckResult",
    "PermissionEngine",
    "PermissionMode",
]
