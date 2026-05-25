"""
Scraper Guadeloupe - PDFs "voltaïque" (2010-2017)
"""

import asyncio
import logging
import os
import re
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from urllib.parse import urljoin

import httpx
import pandas as pd

from ..config import get_http_client, project_filter
from ..utils.data import get_scraped_avis_dict
from ..utils.download import download_pdfs
from ..utils.scraping import get_soup_from_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://www.guadeloupe.developpement-durable.gouv.fr"


async def fetch_year_urls_from_index(client: httpx.AsyncClient) -> dict:
    """
    Récupère automatiquement les URLs de chaque année depuis les pages d'index.
    Couvre les deux pages de pagination.
    """
    year_urls = {}
    index_pages = [
        f"{ARCHIVE_URL}/annees-2010-a-2022-r1437.html",
        f"{ARCHIVE_URL}/annees-2010-a-2022-r1437.html?debut_listearticles=8",
    ]

    for index_url in index_pages:
        logger.debug("  Récupération de l'index : %s", index_url)
        soup = await get_soup_from_url(client, index_url)
        for h2 in soup.find_all("h2"):
            a_tag = h2.find("a")
            if not a_tag:
                continue
            year_text = a_tag.get_text(strip=True)
            href = a_tag.get("href", "")
            if year_text.isdigit():
                year = int(year_text)
                if 2010 <= year <= 2017:
                    year_urls[year] = href
                    logger.debug("Année %s → %s", year, href)

    return year_urls


def extract_date_from_label(label_text: str) -> datetime | None:
    match_o = re.search("[0-9]{1,2}/[0-9]{1,2}/[0-9]{4}", label_text)

    publish_date = None
    if match_o is not None:
        publish_date_raw = match_o.group()
        publish_date = datetime.strptime(publish_date_raw, "%d/%m/%Y")

    return publish_date


async def find_pdfs_for_year(client: httpx.AsyncClient, year: int, url: str) -> list:
    """
    Parse la page d'une année et retourne la liste des PDFs
    dont la ligne de tableau contient 'voltaïque'/'voltaique'.
    Retourne une liste de dicts : {label, pdf_url, year}
    """
    full_url = urljoin(ARCHIVE_URL, url)
    logger.debug("--- Année %s : %s ---", year, full_url)

    soup = await get_soup_from_url(client, full_url)

    pdfs_found = []

    # Stratégie 1 : chercher dans les lignes de tableau <tr>
    for tr in soup.find_all("tr"):
        row_text = tr.get_text(" ", strip=True)

        if project_filter(row_text):
            last_col_e = list(tr.find_all("td"))[-1]
            for a_tag in tr.find_all("a", href=True):
                href = a_tag["href"]
                if href.lower().endswith(".pdf"):
                    label = a_tag.get_text(strip=True) or href.split("/")[-1]

                    project_name_e = last_col_e.contents[0]
                    if isinstance(project_name_e, str):
                        project_name = project_name_e.strip()
                    else:
                        project_name = project_name_e.text.strip()

                    pdf_url = urljoin(ARCHIVE_URL, href)

                    pdf_filename = Path(href).name
                    publish_date = extract_date_from_label(label)

                    pdfs_found.append(
                        get_scraped_avis_dict(
                            project_name=project_name,
                            communes_names=None,
                            departement_name="Guadeloupe",
                            project_date=publish_date,
                            pdf_filename=pdf_filename,
                            pdf_url=pdf_url,
                        )
                    )
                    logger.debug("[TROUVÉ] %s", label)
                    logger.debug(pdf_url)

    if not pdfs_found:
        logger.debug("Aucun PDF trouvé pour %s.", year)

    return pdfs_found


async def get_guadeloupe_archive_pdf_urls_and_metadata() -> pd.DataFrame:
    logger.debug("=" * 60)
    logger.debug("Scraper DEAL Guadeloupe - PDFs 'voltaïque' (2010-2017)")
    logger.debug("=" * 60)

    async with get_http_client() as client:
        # Étape 1 : récupérer automatiquement les URLs des années
        logger.debug("[1/3] Récupération des URLs des années depuis l'index...")
        year_urls = await fetch_year_urls_from_index(client=client)

        missing = [y for y in range(2010, 2018) if y not in year_urls]
        if missing:
            logger.debug("⚠  URLs non trouvées pour les années : %s", missing)
            logger.debug("   Vérifiez manuellement la pagination de l'index.")

        # Étape 2 : scraper chaque page d'année
        logger.debug("[2/3] Recherche des PDFs 'voltaïque' par année...")
        all_pdfs = []
        for year in sorted(year_urls.keys()):
            pdfs = await find_pdfs_for_year(client, year, year_urls[year])
            all_pdfs.extend(pdfs)
            await asyncio.sleep(0.5)

    return pd.DataFrame(all_pdfs)


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Program that scrapes the URLs of Guyane's MRAe archive website pages that list PDFs of AE."
        "Output a new CSV file _guyane_archive_pdf_links.csv and downloads the PDF files."
    )
    arg_parser.add_argument(
        "-o",
        "--output_path",
        help="Path where to output the resulting _guyane_archive_pdf_links.csv file and downloaded PDFs files."
        "Default to current working directory.",
        type=Path,
        dest="output_path",
    )
    args = arg_parser.parse_args()

    output_path = Path(os.getcwd())
    if args.output_path is not None:
        output_path = args.output_path

    if not output_path.exists():
        output_path.mkdir(parents=True)

    df = asyncio.run(get_guadeloupe_archive_pdf_urls_and_metadata())
    df.to_csv(output_path / "_guadeloupe_archive_pdf_links.csv", index=False)

    asyncio.run(download_pdfs(df, output_path=output_path))
