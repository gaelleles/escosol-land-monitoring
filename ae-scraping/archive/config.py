import httpx
from httpx_retries import Retry, RetryTransport

TIMEOUT_CONFIG = httpx.Timeout(60.0, connect=10.0)
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
RETRY_TRANSPORT = RetryTransport(retry=Retry(total=5, backoff_factor=0.5))
