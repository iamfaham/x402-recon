import pytest

from x402_recon.retry import (
    BASE_RETRY_DELAY,
    MAX_RETRY_ATTEMPTS,
    TRANSIENT_HTTP_CODES,
    retry_transient,
)


class Boom(RuntimeError):
    """A minimal error carrying the transient flag the retry loop reads."""

    def __init__(self, message="boom", *, transient=False):
        super().__init__(message)
        self.transient = transient


def _recording_sleep():
    waits = []
    return waits, waits.append


def test_a_successful_call_is_returned_without_sleeping():
    waits, sleep = _recording_sleep()
    assert retry_transient(lambda: "ok", sleep=sleep) == "ok"
    assert waits == []


def test_a_non_transient_error_is_raised_immediately():
    waits, sleep = _recording_sleep()
    calls = []

    def send():
        calls.append(1)
        raise Boom("your request was wrong", transient=False)

    with pytest.raises(Boom, match="your request was wrong"):
        retry_transient(send, sleep=sleep)

    assert calls == [1], "a permanent failure must not be retried"
    assert waits == []


def test_a_transient_error_that_recovers_returns_the_later_result():
    waits, sleep = _recording_sleep()
    attempts = []

    def send():
        attempts.append(1)
        if len(attempts) < 3:
            raise Boom("503", transient=True)
        return "recovered"

    assert retry_transient(send, sleep=sleep) == "recovered"
    assert len(attempts) == 3
    assert len(waits) == 2, "one sleep per retry, none after the success"


def test_retries_stop_at_the_attempt_cap_and_re_raise():
    waits, sleep = _recording_sleep()
    attempts = []

    def send():
        attempts.append(1)
        raise Boom("still down", transient=True)

    with pytest.raises(Boom, match="still down"):
        retry_transient(send, sleep=sleep)

    assert len(attempts) == MAX_RETRY_ATTEMPTS
    assert len(waits) == MAX_RETRY_ATTEMPTS - 1


def test_each_delay_falls_within_its_jitter_band():
    # Asserting a band rather than comparing consecutive delays: the jitter
    # ranges of adjacent attempts overlap, so a strict ordering assertion
    # flakes on correct code. The band pins the exponential magnitude too.
    waits, sleep = _recording_sleep()

    def send():
        raise Boom("down", transient=True)

    with pytest.raises(Boom):
        retry_transient(send, sleep=sleep)

    for n, observed in enumerate(waits, start=1):
        expected = BASE_RETRY_DELAY * (2 ** (n - 1))
        assert expected * 0.5 <= observed <= expected * 1.5


def test_every_retry_announces_itself(capsys):
    # Nothing retries silently: a slow run must be explicable.
    waits, sleep = _recording_sleep()

    def send():
        raise Boom("no backend is currently healthy", transient=True)

    with pytest.raises(Boom):
        retry_transient(send, sleep=sleep)

    printed = capsys.readouterr().out.strip().splitlines()
    assert len(printed) == MAX_RETRY_ATTEMPTS - 1
    for line in printed:
        assert "retry" in line
        assert "no backend is currently healthy" in line, "the reason must be named"


def test_an_error_with_no_transient_attribute_is_treated_as_permanent():
    # The loop duck-types on `.transient`; a plain exception must not be
    # retried just because it lacks the attribute.
    waits, sleep = _recording_sleep()
    calls = []

    def send():
        calls.append(1)
        raise ValueError("unrelated")

    with pytest.raises(ValueError):
        retry_transient(send, sleep=sleep)

    assert calls == [1]
    assert waits == []


def test_the_transient_http_codes_are_the_retryable_ones():
    for code in (429, 502, 503, 504):
        assert code in TRANSIENT_HTTP_CODES
    for code in (400, 402, 404, 413, 500):
        assert code not in TRANSIENT_HTTP_CODES
