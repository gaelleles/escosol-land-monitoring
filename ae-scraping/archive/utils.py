import logging
from pathlib import Path
import re

import httpx
import pandas as pd
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm

from .config import HEADERS, RETRY_TRANSPORT, TIMEOUT_CONFIG

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def download_pdf(pdf_url: str, pdf_output_path: Path):
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

    Raises
    ------
    httpx.HTTPError
        If there is an error during any HTTP request.
    FileNotFoundError
        If the `output_path` directory does not exist.
    KeyError
        If the DataFrame is missing required columns ('pdf_url' or 'pdf_filename').
    """
    for _, row in pdf_metadata_df.iterrows():
        _ = await download_pdf(row["pdf_url"], output_path / row["pdf_filename"])


def clean_departement_code(raw_departement_code: str) -> str | None:
    """Try to clean raw_departement_code to get consistent 2 to 3 digits departement format (3 digits for Overseas)"""
    if len(raw_departement_code) == 2:
        return raw_departement_code

    if len(raw_departement_code) == 5:
        if ("A" in raw_departement_code) or ("B" in raw_departement_code):
            return raw_departement_code[:2]

        try:
            raw_departement_code_int = int(raw_departement_code)
        except Exception:
            return None

        if raw_departement_code_int > 97000:
            # Overseas case
            return raw_departement_code[:3]

        return raw_departement_code[:2]


def extract_departement(string: str) -> str | None:
    """Extract departement code from a string like the title of an AE"""
    departement_code = None

    departement_match = re.search(r"\(([0-9AB]{2,5})\)", string)
    if departement_match is not None:
        departement_code = departement_match.group(1)
        return clean_departement_code(departement_code)
