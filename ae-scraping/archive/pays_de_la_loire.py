"""
Module containing utilities to scrape Pays de la Loire archive website
(https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/archives-ex-aquitaine-ex-limousin-ex-poitou-r3920.html)
and extract relevant AE metadata and PDFs.
"""

import asyncio
import locale
import logging
import random
from asyncio import Semaphore
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import pandas as pd
from bs4.element import PageElement
from httpx import AsyncClient
from tqdm.asyncio import tqdm_asyncio
from tqdm.contrib.logging import logging_redirect_tqdm

from ..config import get_http_client, project_filter
from ..utils.data import get_scraped_avis_dict
from ..utils.scraping import get_soup_from_url

locale.setlocale(locale.LC_ALL, "fr_FR.UTF-8")

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://www.pays-de-la-loire.developpement-durable.gouv.fr/avis-emis-par-l-autorite-environnementale-r469.html"


async def get_pdl_archive_pdf_urls_and_metadata() -> pd.DataFrame:
    """Extract AE PDF links and metadata from Pays de la Loire AE
    archive website.

    Scrapes the archives to find relevant AEs,
    extracting project names, commune information, departement details, and
    associated PDF document URLs.

    Returns
    -------
    pd.DataFrame
        DataFrame containing extracted avis with columns:
        - project_name : str
            Name of the photovoltaic/solar project
        - commune_name : str
            Name of the commune where the project is located
        - departement_name : str
            Name of the departement
        - year : str
            Year when the avis was published (if available)
        - pdf_filename : str or None
            Filename of the PDF document
        - pdf_url : str
            Full URL to the PDF document

    Examples
    --------
    >>> import asyncio
    >>> df = asyncio.run(get_pdl_archive_pdf_urls_and_metadata())
    """
    avis = []

    year_links = {}
    async with get_http_client() as client:
        years_page_soup = await get_soup_from_url(client, ARCHIVE_URL)
        year_links_elements = years_page_soup.select_one(
            "div.liste-rubriques"
        ).find_all("a", class_="fr-tile__link")

        for year_e in year_links_elements:
            link_text = year_e.get_text(strip=True)
            if link_text == "Avis émis à partir de 2021":
                continue

            year = int(link_text.replace("Année ", ""))
            url = year_e.get("href")

            year_links[year] = urljoin(ARCHIVE_URL, url)

        sem = Semaphore(5)
        year_departement_links = []
        async with sem:
            couroutines = [
                extract_year_departements_links(client, url, year, sem)
                for year, url in year_links.items()
            ]
            gather_results = await tqdm_asyncio.gather(
                *couroutines, desc="Extracting PDL yearly links", leave=False
            )

            for res in gather_results:
                year_departement_links.extend(res)

        async with sem:
            couroutines = [
                extract_avis_from_year_departement_page(
                    client, e["url"], e["year"], e["departement_name"], sem
                )
                for e in year_departement_links
            ]
            gather_results = await tqdm_asyncio.gather(
                *couroutines, desc="Extracting PDF archive avis", leave=False
            )

            for res in gather_results:
                avis.extend(res)
    return pd.DataFrame(avis)


async def extract_year_departements_links(
    client: AsyncClient, year_url: str, year: int, semaphore: asyncio.Semaphore
) -> list[dict[str, Any]]:
    """Extract departement links from a given year's archive page.

    Parses the HTML content of a yearly archive page to identify and
    collect links to individual departement pages.

    Parameters
    ----------
    client : AsyncClient
        The HTTPX async client used for fetching the page.
    year_url : str
        The URL of the page containing the list of departements for a specific year.
    year : int
        The year associated with the archive page.
    semaphore : asyncio.Semaphore
        Semaphore for rate limiting.

    Returns
    -------
    list[dict[str, Any]]
        A list of dictionaries containing departement information. Each dictionary has:
        - year (int): The year of the archive.
        - departement_name (str): The name of the departement.
        - url (str): The full URL to the departement's page.

    Notes
    -----
    Includes a random sleep delay to avoid overwhelming the server.
    """
    async with semaphore:
        soup = await get_soup_from_url(client, year_url)
    departements_links_elements = soup.find_all(
        "a", class_="fr-card__link article-card-lien"
    )

    departements_links = []
    for dep_e in departements_links_elements:
        departement_name = dep_e.get_text(strip=True)
        departement_url = dep_e.get("href")

        departements_links.append(
            {
                "year": year,
                "departement_name": departement_name,
                "url": urljoin(ARCHIVE_URL, departement_url),
            }
        )

    await asyncio.sleep(random.uniform(0.7, 2.9))
    return departements_links


async def extract_avis_from_year_departement_page(
    client: AsyncClient,
    year_departement_url: str,
    year: int,
    departement_name: str,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """Extract relevant "Avis Environnementaux" (AE) metadata from a departement page.

    Parses the HTML content of a specific departement's page to extract
    metadata for each environmental assessment (avis), including project
    names, commune names, dates, and PDF links.

    Parameters
    ----------
    client : AsyncClient
        The HTTPX async client used for fetching the page.
    year_departement_url : str
        The URL of the departement's archive page.
    year : int
        The year associated with the AE.
    departement_name : str
        The name of the departement.
    semaphore : asyncio.Semaphore
        Semaphore for rate limiting.

    Returns
    -------
    list[dict[str, Any]]
        A list of dictionaries containing extracted AE metadata. Each dictionary includes:
        - project_name (str): Name of the project.
        - communes_names (list[str] or None): List of commune names.
        - departement_name (str): Name of the departement.
        - project_date (datetime): Date of the AE.
        - pdf_filename (str or None): Filename of the PDF.
        - pdf_url (str): Full URL to the PDF.

    Notes
    -----
    Includes a random sleep delay to avoid overwhelming the server.
    """
    async with semaphore:
        soup = await get_soup_from_url(client, year_departement_url)

    article_body_element = soup.select_one("div.texte-article.fr-text")

    avis = []
    communes_names = None
    project_name = None
    skip_avis = False
    for child in article_body_element.contents:
        if child == "\n":
            continue
        elif child.name == "h2":
            communes_names_raw = child.get_text(strip=True).split(",")
            communes_names = [e.strip() for e in communes_names_raw]
        elif child.name == "p":
            candidate_project_name = child.get_text(strip=True)
            if project_filter(candidate_project_name):
                project_name = candidate_project_name
                skip_avis = False
            if not next_sibling_is_link(child):
                skip_avis = True
        elif child.name == "div":
            if skip_avis or (project_name is None):
                skip_avis = False
                continue

            avis_link_element = child.find("a")
            pdf_url = avis_link_element.get("href")
            pdf_name = Path(pdf_url).name

            date_raw = avis_link_element.contents[0]
            avis_date = None
            try:
                avis_date = datetime.strptime(
                    date_raw.lower()
                    .replace("avis signé le", "")
                    .replace("_", " ")
                    .strip(),
                    "%d %B %Y",
                )
            except Exception as exc:
                avis_date = datetime(year, 1, 1)
                logger.debug(exc)

            avis_dict = get_scraped_avis_dict(
                project_name=project_name,
                communes_names=communes_names,
                departement_name=departement_name,
                project_date=avis_date,
                pdf_filename=pdf_name,
                pdf_url=urljoin(ARCHIVE_URL, pdf_url),
            )
            avis.append(avis_dict)
            project_name = None

    await asyncio.sleep(random.uniform(0.5, 3.9))
    return avis


def next_sibling_is_link(element: PageElement) -> bool:
    """Check if the next relevant sibling element contains a div with a link.

    Iterates through the next siblings of an HTML element to determine
    if a link (specifically within a `<div>`) appears before any
    section headers (`<h2>`) or the end of the siblings.

    Parameters
    ----------
    element : PageElement
        The BeautifulSoup element to check siblings for.

    Returns
    -------
    bool
        True if a link is found in a sibling `<div>` before an `<h2>` tag
        or end of siblings; False otherwise.
    """
    for sibl_e in element.next_siblings:
        if isinstance(sibl_e, str):
            continue

        if sibl_e.name == "div":
            return True

        if sibl_e.name == "h2":
            return False

    return False


if __name__ == "__main__":
    with logging_redirect_tqdm():
        asyncio.run(get_pdl_archive_pdf_urls_and_metadata())
