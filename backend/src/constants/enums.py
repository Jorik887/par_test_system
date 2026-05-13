from enum import Enum


class TestStatus(str, Enum):
    __test__ = False
    PENDING = "pending"
    RUNNING = "running"
    SUCCESS = "success"
    FAILED = "failed"
