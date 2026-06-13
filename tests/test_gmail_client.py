"""Tests for the Gmail client retry/backoff (Task 2.3)."""

from __future__ import annotations

import pytest
from app.mail.gmail import client as gmail_client
from googleapiclient.errors import HttpError


class _Resp:
    def __init__(self, status):
        self.status = status
        self.reason = "err"


class _Request:
    def __init__(self, fail_times, status=429):
        self.fail_times = fail_times
        self.status = status
        self.calls = 0

    def execute(self):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise HttpError(resp=_Resp(self.status), content=b"err")
        return {"ok": True}


def test_retries_transient_then_succeeds():
    req = _Request(fail_times=2, status=503)
    result = gmail_client._execute(req, _sleep=lambda _d: None)
    assert result == {"ok": True}
    assert req.calls == 3  # two failures + one success


def test_non_transient_error_propagates():
    req = _Request(fail_times=1, status=400)
    with pytest.raises(HttpError):
        gmail_client._execute(req, _sleep=lambda _d: None)
    assert req.calls == 1  # not retried
