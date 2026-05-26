import httpx
from httpx_retries import Retry, RetryTransport

TIMEOUT_CONFIG = httpx.Timeout(180.0, connect=90.0, read=490)
HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Connection": "close",
}
RETRY_TRANSPORT = RetryTransport(
    retry=Retry(
        total=8,
        backoff_factor=3,
        max_backoff_wait=30,
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


def get_http_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        headers=HEADERS,
        timeout=TIMEOUT_CONFIG,
        follow_redirects=True,
        transport=RETRY_TRANSPORT,
    )


def project_filter(text: str) -> bool:
    """Returns `true` if any of "solaire", "voltaïque"or "voltaique" is in `text`."""
    return any(e in text.lower() for e in ["solaire", "voltaïque", "voltaique"])
