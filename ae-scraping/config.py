import httpx
from httpx_retries import Retry, RetryTransport

TIMEOUT_CONFIG = httpx.Timeout(90.0, connect=30.0, read=490)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Connection": "close",
}
RETRY_TRANSPORT = RetryTransport(
    retry=Retry(
        total=5,
        backoff_factor=2,
        retry_on_exceptions=[
            httpx.TimeoutException,
            httpx.NetworkError,
            httpx.RemoteProtocolError,
            httpx.ReadError,
            httpx.ConnectTimeout,
            httpx.ReadTimeout,
        ],
    )
)
