"""
Module containing utilities to scrape Corse AE archive website
(https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/archives-ex-aquitaine-ex-limousin-ex-poitou-r3920.html)
and extract relevant AE metadata and PDFs.
"""

import asyncio
import locale
import logging
import math
import re
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import pandas as pd
from bs4 import BeautifulSoup
from tqdm.asyncio import tqdm_asyncio

from ..config import (
    get_http_client,
    project_filter,
)
from ..utils.data import get_scraped_avis_dict
from ..utils.scraping import get_soup_from_url

locale.setlocale(locale.LC_ALL, "fr_FR.UTF-8")

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://www.corse.developpement-durable.gouv.fr/projets-r643.html#pagination_listearticles"


async def get_corse_archive_pdf_urls_and_metadata() -> pd.DataFrame:
    """Extract AE PDF links and metadata from Corse AE
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

    async with get_http_client() as client:
        soup = await get_soup_from_url(client, ARCHIVE_URL)
        years_links = build_year_pages_urls(soup, ARCHIVE_URL)

        project_links = []
        for link in years_links:
            projects_page_soup = await get_soup_from_url(client, link)
            project_elements = projects_page_soup.find_all(
                "a", class_="fr-card__link article-card-lien"
            )
            for el in project_elements:
                project_page_link = el.get("href")
                year = int(el.get_text(strip=True).replace("Projets ", ""))
                project_links.append(
                    {"year": year, "url": urljoin(ARCHIVE_URL, project_page_link)}
                )

        avis = await get_all_avis_from_year_projects_pages_urls(client, project_links)
    return pd.DataFrame(avis)


def build_year_pages_urls(soup: BeautifulSoup, first_page_url: str) -> list[str]:
    """
    Builds a list of URLs for all pages of a projects years listings.

    Parses the pagination element of the provided BeautifulSoup object to determine
    the total number of pages and constructs the corresponding URLs.

    Parameters
    ----------
    soup : BeautifulSoup
        The parsed HTML content of the first page.
    first_page_url : str
        The URL of the first page.

    Returns
    -------
    list[str]
        List of URLs for all pages in the pagination sequence.
    """
    urls = [urljoin(ARCHIVE_URL, first_page_url)]

    ul_element = soup.find("ul", class_="fr-pagination__list")
    if ul_element is None:
        return urls

    pagination_elements = ul_element.find_all("a")

    last_page_number = None
    last_page_url = None
    for li_e in reversed(pagination_elements):
        raw_text = li_e.get_text(strip=True)
        if (match_o := re.fullmatch(r"([0-9]*)", raw_text)) is not None:
            last_page_number = int(match_o.group(1))
            last_page_url: str = li_e.get("href")
            break

    max_offset_match_o = re.search(r"debut_listearticles=([0-9]+)", last_page_url)
    last_offset = int(max_offset_match_o.group(1))
    step = math.ceil(last_offset / (last_page_number - 1))

    for offset in range(step, last_offset + step, step):
        urls.append(
            urljoin(
                ARCHIVE_URL,
                re.sub(
                    r"debut_listearticles=[0-9]+",
                    f"debut_listearticles={offset}",
                    last_page_url,
                ),
            )
        )

    return urls


async def get_all_avis_from_year_projects_pages_urls(
    client: httpx.AsyncClient, year_projects_links: list[dict]
) -> list[dict]:
    avis = []
    sem = asyncio.Semaphore(5)
    coroutines = []

    for e in year_projects_links:
        coroutines.append(
            get_avis_from_year_projects_page(client, e["url"], e["year"], sem)
        )

    res = []

    res = await tqdm_asyncio.gather(*coroutines, desc="Corse archive AE scraping")

    for res_list in res:
        avis.extend(res_list)

    return avis


async def get_avis_from_year_projects_page(
    client: httpx.AsyncClient, url: str, year: int, semaphore: asyncio.Semaphore
) -> list[dict]:
    avis = []

    async with semaphore:
        soup = await get_soup_from_url(client, url)

    ul_elements = soup.select("div.texte-article.fr-text > ul")

    for ul_e in ul_elements:
        first_li_e = ul_e.find("li")
        if first_li_e.find("ul") is not None:
            first_li_e = first_li_e.find("ul").find("li")

        a_e = first_li_e.find("a")

        if a_e is None:
            continue

        avis_first_part_text = a_e.contents[0]
        avis_second_part_text = ""
        avis_second_part_e = first_li_e.find("div")
        if (e := avis_second_part_e.find("p", class_="fr-download__desc")) is not None:
            avis_second_part_text = e.get_text(strip=True)
        elif (e := avis_second_part_e.next_sibling) is not None:
            avis_second_part_text = e

        project_name: str = (
            avis_first_part_text.strip() + " " + avis_second_part_text.strip()
        )

        if project_filter(project_name):
            pdf_url = a_e.get("href")
            pdf_name = Path(pdf_url).name
            departement_name = extract_department_name_from_project_name(project_name)
            avis_date = extract_project_date_from_project_name(
                project_name
            ) or datetime(year, 1, 1)

            avis.append(
                get_scraped_avis_dict(
                    project_name=project_name,
                    communes_names=None,
                    departement_name=departement_name,
                    project_date=avis_date,
                    pdf_filename=pdf_name,
                    pdf_url=urljoin(ARCHIVE_URL, pdf_url),
                )
            )

    return avis


def extract_department_name_from_project_name(project_name: str) -> str | None:
    project_name_clean = project_name.lower()

    departement_name = None
    if ("corse du sud" in project_name_clean) or ("corse-du-sud" in project_name_clean):
        departement_name = "Corse-du-Sud"
    elif ("haute corse" in project_name_clean) or ("haute-corse" in project_name_clean):
        departement_name = "Haute-Corse"

    return departement_name


def extract_project_date_from_project_name(project_name: str) -> datetime | None:
    pattern_1 = re.compile(
        r"du ([0-9]{1,2}(?:er)? [a-zéù]+ [0-9]{4})", flags=re.IGNORECASE
    )
    pattern_2 = re.compile(
        r"du ([0-9]{1,2}\/[0-9]{1,2}\/[0-9]{4})", flags=re.IGNORECASE
    )

    match_o = re.search(pattern_1, project_name)
    if match_o is not None:
        date_raw = match_o.group(1).replace("/", " ").replace("er", "")
        try:
            avis_date = datetime.strptime(date_raw, "%d %B %Y")
            return avis_date
        except Exception as exc:
            logger.debug(exc)

    match_o = re.search(pattern_2, project_name)
    if match_o is not None:
        date_raw = match_o.group(1)
        try:
            avis_date = datetime.strptime(date_raw, "%d/%m/%Y")
            return avis_date
        except Exception as exc:
            logger.debug(exc)

    return None


if __name__ == "__main__":
    asyncio.run(get_corse_archive_pdf_urls_and_metadata())
