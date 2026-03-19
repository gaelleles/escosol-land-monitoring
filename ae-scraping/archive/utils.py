import logging
from pathlib import Path

import httpx
import pandas as pd
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from .config import HEADERS, RETRY_TRANSPORT, TIMEOUT_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def download_pdf(pdf_url: str, pdf_output_path: Path):
    with logging_redirect_tqdm():
        with pdf_output_path.open(mode="wb") as f:
            async with httpx.AsyncClient(
                headers=HEADERS,
                timeout=TIMEOUT_CONFIG,
                follow_redirects=True,
                transport=RETRY_TRANSPORT,
            ) as client:
                async with client.stream("GET", pdf_url) as response:
                    total = int(response.headers["Content-Length"])

                    with tqdm(
                        total=total,
                        unit_scale=True,
                        unit_divisor=1024,
                        unit="B",
                        desc=f"Downloading PDF from {pdf_url}",
                    ) as progress:
                        num_bytes_downloaded = response.num_bytes_downloaded
                        async for chunk in response.aiter_bytes():
                            f.write(chunk)
                            progress.update(
                                response.num_bytes_downloaded - num_bytes_downloaded
                            )
                            num_bytes_downloaded = response.num_bytes_downloaded


async def download_pdfs(pdf_metadata_df: pd.DataFrame, output_path: Path):
    for _, row in pdf_metadata_df.iterrows():
        _ = await download_pdf(row["pdf_url"], output_path / row["pdf_filename"])
