"""Shared retry policy for the two modules that touch the network.

`rpc.py` and `discover.py` classify their errors differently - one talks
JSON-RPC, the other reads a 402 body - but they need the same answer to the
same question: this failure is the endpoint having a bad moment, so wait and
ask again rather than giving up or making the problem worse.

Keeping the loop here means the two cannot drift apart. Tuning the backoff
in one place tunes it everywhere, which is the point.
"""

import random
import time

# Codes that mean "try again shortly", not "your request was wrong".
# 503 is what mainnet.base.org actually returned three times consecutively
# during the first real run against it.
TRANSIENT_HTTP_CODES = frozenset({429, 502, 503, 504})

MAX_RETRY_ATTEMPTS = 4
MAX_RETRY_SECONDS = 30.0
BASE_RETRY_DELAY = 0.5


def retry_transient(send, *, sleep=time.sleep):
    """Call `send`, retrying transient failures with jittered exponential backoff.

    A failure is retryable when the exception carries a truthy `transient`
    attribute; `RpcError` and `DiscoveryError` both set it at the point where
    they know what the endpoint said. Anything else - including an exception
    with no such attribute - is raised immediately, because retrying a request
    the endpoint rejected on its merits only wastes the caller's time.

    Bounded by both the attempt count and the cumulative wall clock, so a dead
    endpoint fails in seconds rather than hanging.

    Nothing retries silently: a slow run must be explicable rather than
    mysterious, which is the same guarantee the reject list gives for data.
    """
    attempt = 0
    slept = 0.0
    while True:
        try:
            return send()
        except Exception as exc:
            if not getattr(exc, "transient", False):
                raise
            attempt += 1
            if attempt >= MAX_RETRY_ATTEMPTS or slept >= MAX_RETRY_SECONDS:
                raise
            delay = BASE_RETRY_DELAY * (2 ** (attempt - 1))
            delay *= random.uniform(0.5, 1.5)  # jitter: avoid a thundering herd
            delay = min(delay, MAX_RETRY_SECONDS - slept)
            print(f"  retry {attempt}/{MAX_RETRY_ATTEMPTS} in {delay:.1f}s: {exc}")
            sleep(delay)
            slept += delay
