import asyncio
import logging
import random
from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import urljoin

import httpx
import pandas as pd
from bs4 import BeautifulSoup
from tqdm.asyncio import tqdm_asyncio
from tqdm.contrib.logging import logging_redirect_tqdm

from ..config import HEADERS, RETRY_TRANSPORT, TIMEOUT_CONFIG

logging.basicConfig()
logger = logging.getLogger(__name__)

SEMAPHORE = asyncio.Semaphore(5)  # Max 5 concurrent requests


async def get_pdf_metadata(
    client: httpx.AsyncClient, base_url: str
) -> list[dict] | None:
    """
    Récupère les métadonnées des PDF liés aux encadrés
    contenant les mots-clés "voltaïque" ou "voltaique" ou "solaire"
    sur les pages avis de recherche par année.

    :param base_url: url de la page d'avis de recherche région x année MRAE
    """

    results = []

    response = await client.get(base_url)
    soup = BeautifulSoup(response.text, "html.parser")

    encadres = soup.select("div.texteencadre-spip")
    for div in encadres:
        texte_complet = (
            div.get_text(" ", strip=True).lower().replace("ï", "i")
        )  # Normalisation des caractères, + efficace que chercher par accent

        if any(e in texte_complet for e in ["voltaique", "solaire"]):
            strong_tag = div.find("strong")
            title = strong_tag.get_text(strip=True) if strong_tag else "Sans titre"

            pdf_link = div.select_one("a.fr-download__link")
            if pdf_link and pdf_link.get("href"):
                pdf_url = urljoin(base_url, pdf_link["href"])
                pdf_name = pdf_url.split("/")[-1]

                results.append(
                    {
                        "project_name": title,
                        "description": texte_complet,
                        "pdf_url": pdf_url,
                        "pdf_filename": pdf_name,
                    }
                )

    if results:
        return results


async def get_pdf_metadata_sema(
    client: httpx.AsyncClient, base_url: str
) -> list[dict] | None:
    """Wrapper that applies semaphore for rate limiting."""
    async with SEMAPHORE:
        await asyncio.sleep(random.uniform(0.3, 2))

        return await get_pdf_metadata(client, base_url)


async def get_all_pdfs_metadata_df(ae_year_links_df: pd.DataFrame) -> pd.DataFrame:
    """Extract PDF metadata from all year links in parallel using a dataframe of
    links for each region and each year."""

    # Create tasks for all URLs to process concurrently
    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=TIMEOUT_CONFIG,
        follow_redirects=True,
        transport=RETRY_TRANSPORT,
    ) as client:
        tasks = [
            get_pdf_metadata_sema(client, row["year_url"])
            for _, row in ae_year_links_df.iterrows()
        ]

        # Execute all tasks concurrently with progress tracking

        with logging_redirect_tqdm():
            async with SEMAPHORE:
                results_list = await tqdm_asyncio.gather(
                    *tasks,
                    desc="Extracting PDF urls and metadata",
                    unit=" links scraped",
                )

    # Flatten and filter results
    results = []
    for i, result in enumerate(results_list):
        if isinstance(result, Exception):
            url = ae_year_links_df.iloc[i]["year_url"]
            logger.warning(f"Error processing {url}: {result}")
        elif result:  # Only add non-empty results
            results.extend(result)

    return pd.DataFrame(results)


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        "extract_relevant_pdf_links",
        description="Program that scrapes the links of PDF that are relevant for the project. "
        "Also extracts metadata from the PDF web page."
        "Needs the CSV file ae_year_links.csv as input."
        "Output a new CSV file metadata_pdfs.csv.",
    )
    arg_parser.add_argument(
        "ae_year_links_csv_filepath", help="Path to the csv file ae_year_links.csv."
    )
    arg_parser.add_argument(
        "-o",
        "--output_path",
        help="Path where to output the resulting metadata_pdfs.csv file."
        "Default to same folder as ae_year_links.csv.",
        dest="output_path",
    )

    args = arg_parser.parse_args()
    ae_year_links_csv_filepath = Path(args.ae_year_links_csv_filepath)
    output_path = ae_year_links_csv_filepath.parent
    if args.output_path is not None:
        output_path = Path(args.output_path)

    results = []
    year_links = pd.read_csv(ae_year_links_csv_filepath)

    df_results = asyncio.run(get_all_pdfs_metadata_df(year_links))
    df_results.to_csv(output_path / "metadata_pdfs.csv", index=False)
