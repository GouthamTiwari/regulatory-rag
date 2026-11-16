"""Retry a Bedrock call when AWS says "slow down" or is briefly unavailable.

boto3's own adaptive retries already handle most of this. This thin layer adds a few
patient retries on top, and makes the behaviour testable with fake clients (which have no
boto3 retry logic of their own).
"""

import time
from collections.abc import Callable

from botocore.exceptions import ClientError

RETRYABLE_CODES = {
    "ThrottlingException",
    "TooManyRequestsException",
    "ServiceUnavailableException",
    "ModelNotReadyException",
    "InternalServerException",
}


def with_retries[T](
    call: Callable[[], T],
    *,
    attempts: int = 4,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """Run `call`, retrying retryable AWS errors with growing pauses (1 s, 2 s, 4 s)."""
    for attempt in range(1, attempts + 1):
        try:
            return call()
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code not in RETRYABLE_CODES or attempt == attempts:
                raise
            sleep(2.0 ** (attempt - 1))
    raise AssertionError("unreachable")  # the loop always returns or raises
