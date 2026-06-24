import asyncio
import logging
from pathlib import Path
import random

import httpx
import pandas as pd
from tqdm.asyncio import tqdm_asyncio
from tqdm.contrib.logging import logging_redirect_tqdm

from ..config import get_http_client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DOWNLOAD_SEMAPHORE = asyncio.Semaphore(5)  # Max 5 concurrent downloads


async def download_pdf(client: httpx.AsyncClient, pdf_url: str, pdf_output_path: Path):
    """Download an AE PDF file from a URL with progress tracking.

    Downloads the specified AE PDF file asynchronously and saves it to the given output path.
    Displays a progress bar showing download progress in real-time.

    Parameters
    ----------
    pdf_url : str
        The URL of the PDF file to download.
    pdf_output_path : Path
        The local file path where the downloaded PDF will be saved.

    Raises
    ------
    httpx.HTTPError
        If there is an error during the HTTP request (e.g., connection issues,
        invalid response).
    FileNotFoundError
        If the parent directory of `pdf_output_path` does not exist.
    """
    with logging_redirect_tqdm():
        with pdf_output_path.open(mode="wb") as f:
            async with client.stream("GET", pdf_url) as response:
                try:
                    total = int(response.headers["Content-Length"])

                    with tqdm_asyncio(
                        total=total,
                        unit_scale=True,
                        unit_divisor=1024,
                        unit="B",
                        desc=f"Downloading PDF {pdf_output_path.name}",
                    ) as progress:
                        num_bytes_downloaded = response.num_bytes_downloaded
                        async for chunk in response.aiter_bytes():
                            f.write(chunk)
                            progress.update(
                                response.num_bytes_downloaded - num_bytes_downloaded
                            )
                            num_bytes_downloaded = response.num_bytes_downloaded
                except Exception as e:
                    logger.warning(f"Error for {pdf_url}: {str(e)}")
                    return False

    return True


async def download_pdf_sema(
    client: httpx.AsyncClient, pdf_url: str, pdf_output_path: Path
):
    """Wrapper that applies semaphore for rate limiting."""
    async with DOWNLOAD_SEMAPHORE:
        # Add small random delay to appear more human-like
        await asyncio.sleep(random.uniform(0.3, 1.0))
        return await download_pdf(client, pdf_url, pdf_output_path)


async def download_pdfs(
    pdf_metadata_df: pd.DataFrame, output_path: Path, skip_existing: bool = True
):
    """Download multiple AE PDF files from a DataFrame of AE metadata.

    Iterates through each row in the provided DataFrame and downloads the corresponding
    PDF file to the specified output directory using the URL and filename from each row.

    Parameters
    ----------
    pdf_metadata_df : pd.DataFrame
        A pandas DataFrame containing at least two columns: 'pdf_url' (the download
        URL for each PDF) and 'pdf_filename' (the local filename to save as).
    output_path : Path
        The directory path where all downloaded PDF files will be saved.
    skip_existing: bool
        If True, skip existing pdfs (only if their size is >0)

    Raises
    ------
    httpx.HTTPError
        If there is an error during any HTTP request.
    FileNotFoundError
        If the `output_path` directory does not exist.
    KeyError
        If the DataFrame is missing required columns ('pdf_url' or 'pdf_filename').
    """
    # Ensure output directory exists
    output_path.mkdir(parents=True, exist_ok=True)

    # Validate required columns
    required_cols = ["pdf_url", "pdf_filename"]
    missing_cols = [col for col in required_cols if col not in pdf_metadata_df.columns]
    if missing_cols:
        raise KeyError(f"Missing required columns: {missing_cols}")

    logger.info(f"Starting download of {len(pdf_metadata_df)} PDFs...")

    # Create shared client for efficiency
    async with get_http_client() as client:
        tasks = []
        for _, row in pdf_metadata_df.iterrows():
            pdf_filename: str = row["pdf_filename"]
            output_pdf_path = output_path / pdf_filename
            if output_pdf_path.exists() and output_pdf_path.stat().st_size > 0:
                continue

            awaitable = download_pdf_sema(
                client,
                row["pdf_url"],
                output_pdf_path,
            )
            tasks.append(awaitable)

        # Execute all downloads concurrently with progress tracking
        results = await tqdm_asyncio.gather(
            *tasks, desc="Downloading PDFs", colour="BLUE"
        )

    # Calculate statistics
    success_count = sum(1 for r in results if r is True)
    failed_count = len(results) - success_count

    logger.info(f"Download complete: {success_count}/{len(results)} successful")

    if failed_count > 0:
        logger.warning(f"{failed_count} downloads failed. Check logs for details.")

    return {
        "total": len(pdf_metadata_df),
        "success": success_count,
        "failed": failed_count,
    }
