"""
Module containing utilities to scrape Occitanie archive website
(https://www.occitanie.developpement-durable.gouv.fr/avis-de-l-autorite-environnementale-est-ex-r1054.html)
and extract relevant AE metadata and PDFs.
"""

import asyncio
import locale
import logging
import math
import random
from asyncio import Semaphore
from datetime import datetime
from pathlib import Path
import re
from typing import Any
from urllib.parse import urljoin

from bs4 import BeautifulSoup
import pandas as pd
from httpx import AsyncClient
from tqdm.asyncio import tqdm_asyncio

from ..config import get_http_client, project_filter
from ..utils.data import get_scraped_avis_dict
from ..utils.scraping import get_soup_from_url

locale.setlocale(locale.LC_ALL, "fr_FR.UTF-8")

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

PROJECTS_ARCHIVE_URLS = {
    "Aude": "https://www.occitanie.developpement-durable.gouv.fr/production-et-transport-d-energie-dont-icpe-r1030.html",
    "Gard": "https://www.occitanie.developpement-durable.gouv.fr/production-et-transport-d-energie-dont-icpe-r1035.html",
    "Hérault": "https://www.occitanie.developpement-durable.gouv.fr/production-et-transport-d-energie-dont-icpe-r1041.html",
    "Lozère": "https://www.occitanie.developpement-durable.gouv.fr/production-et-transport-d-energie-dont-icpe-r1046.html",
    "Pyrénées-Orientales": "https://www.occitanie.developpement-durable.gouv.fr/production-et-transport-d-energie-dont-icpe-r1051.html",
}
CAS_PAR_CAS_ARCHIVE_URL = "https://www.occitanie.developpement-durable.gouv.fr/decision-de-l-autorite-environnementale-est-sur-r8384.html"


async def get_occitanie_archive_pdf_urls_and_metadata() -> pd.DataFrame:
    """Extract AE PDF links and metadata from the Occitanie AE archive website.

    Scrapes both the projects archive (by departement) and the cas par cas archive
    to find relevant avis environnementaux (AE), extracting project names, commune
    information, departement details, and associated PDF document URLs.

    Returns
    -------
    pd.DataFrame
        DataFrame containing extracted avis with columns including
        "project_name", "communes_names", "departement_name", "project_date",
        "pdf_filename", and "pdf_url".

    Examples
    --------
    >>> import asyncio
    >>> df = asyncio.run(get_occitanie_archive_pdf_urls_and_metadata())
    """
    avis = []

    async with get_http_client() as client:
        cas_par_cas_avis = await get_cas_par_cas_avis(client)
        avis.extend(cas_par_cas_avis)

        all_listings_pages_urls = []
        for departement_name, departement_url in PROJECTS_ARCHIVE_URLS.items():
            soup = await get_soup_from_url(client, departement_url)
            urls = build_listing_pages_urls(soup, departement_url)

            for url in urls:
                all_listings_pages_urls.append(
                    {"departement_name": departement_name, "url": url}
                )

        sem = Semaphore(6)
        all_avis_pages_links = await execute_coroutines(
            [
                get_avis_pages_links_from_listing_page(
                    client, e["url"], e["departement_name"], sem
                )
                for e in all_listings_pages_urls
            ],
            tqdm_desc="Occitanie Archive - Gathering avis pages links",
        )

        all_avis = await execute_coroutines(
            [
                get_avis_from_avis_page_links(
                    client, e["url"], e["departement_name"], sem
                )
                for e in all_avis_pages_links
            ],
            tqdm_desc="Occitanie Archive - Gathering avis",
            list_result=False,
        )
        avis.extend(all_avis)

    return pd.DataFrame(avis)


async def execute_coroutines(
    coroutines: list, tqdm_desc: str | None = None, list_result: bool = True
) -> list[dict]:
    """Execute multiple coroutines concurrently with a progress bar.

    Gathers results from all provided coroutines using tqdm_asyncio.gather.
    If list_result is True, filters out None values and flattens the results
    into a single list. Otherwise, returns results as-is.

    Parameters
    ----------
    coroutines : list
        List of coroutine objects to execute concurrently.
    tqdm_desc : str or None, optional
        Description string for the tqdm progress bar. If None, no progress
        bar is displayed.
    list_result : bool, optional
        If True, filters out None values and extends results into a flat list.
        If False, returns the raw gathered results. Default is True.

    Returns
    -------
    list[dict]
        List of results from the coroutines. When list_result is True, None
        values are removed and nested lists are flattened.

    Examples
    --------
    >>> results = await execute_coroutines(
    ...     [fetch_data(url) for url in urls],
    ...     tqdm_desc="Fetching data"
    ... )
    """
    cor_res = await tqdm_asyncio.gather(*coroutines, desc=tqdm_desc)

    if list_result:
        res = []
        for res_tmp in cor_res:
            if res_tmp is not None:
                res_tmp_filtered = [e for e in res_tmp if e is not None]
                res.extend(res_tmp_filtered)
        return res

    return cor_res


async def get_avis_pages_links_from_listing_page(
    client: AsyncClient,
    departement_listing_page_url: str,
    departement_name: str,
    semaphore: Semaphore,
) -> list[dict]:
    """Extract avis page links from a departement listing page.

    Fetches the HTML content of a departement's avis listing page and extracts
    all project card links. Each link is filtered through the project_filter
    function to ensure relevance.

    Parameters
    ----------
    client : httpx.AsyncClient
        The async HTTP client used for fetching the page content.
    departement_listing_page_url : str
        URL of the listing page for a specific departement.
    departement_name : str
        Name of the departement (e.g., "Aude", "Gard", "Hérault").
    semaphore : asyncio.Semaphore
        Semaphore to control concurrency of HTTP requests.

    Returns
    -------
    list[dict]
        List of dictionaries containing avis page information. Each dictionary
        has keys "departement_name" (str) and "url" (str) pointing to individual
        avis pages.

    Examples
    --------
    >>> links = await get_avis_pages_links_from_listing_page(
    ...     client,
    ...     "https://www.occitanie.../aude-page-1.html",
    ...     "Aude",
    ...     semaphore
    ... )
    """
    avis_links = []

    async with semaphore:
        soup = await get_soup_from_url(client, departement_listing_page_url)

    a_el_list = soup.select("a.fr-card__link.article-card-lien")

    for a_el in a_el_list:
        project_name = a_el.get_text(strip=True)

        if not project_filter(project_name):
            continue

        avis_url = a_el.get("href")
        avis_links.append(
            {
                "departement_name": departement_name,
                "url": urljoin(departement_listing_page_url, avis_url),
            }
        )

    return avis_links


def build_listing_pages_urls(soup: BeautifulSoup, first_page_url: str) -> list[str]:
    """
    Builds a list of URLs for all pages of a departement's year avis listings.

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
    urls = [first_page_url]

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
                first_page_url,
                re.sub(
                    r"debut_listearticles=[0-9]+",
                    f"debut_listearticles={offset}",
                    last_page_url,
                ),
            )
        )

    return urls


async def get_avis_from_avis_page_links(
    client: AsyncClient, url: str, departement_name: str, semaphore: Semaphore
) -> dict:
    """Extract avis metadata from an individual avis page.

    Fetches the HTML content of an avis page and extracts the project name,
    commune names, avis date, and PDF document URL. The commune names are
    extracted from the project name using pattern matching.

    Parameters
    ----------
    client : httpx.AsyncClient
        The async HTTP client used for fetching the page content.
    url : str
        URL of the individual avis page.
    departement_name : str
        Name of the departement to which this avis belongs.
    semaphore : asyncio.Semaphore
        Semaphore to control concurrency of HTTP requests.

    Returns
    -------
    dict
        Dictionary containing avis metadata with keys: "project_name",
        "communes_names", "departement_name", "project_date", "pdf_filename",
        and "pdf_url".

    Examples
    --------
    >>> avis_data = await get_avis_from_avis_page_links(
    ...     client,
    ...     "https://www.occitanie.../avis-123.html",
    ...     "Aude",
    ...     semaphore
    ... )
    """
    async with semaphore:
        soup = await get_soup_from_url(client, url)

    project_name = soup.select_one("h1.titre-article").get_text(strip=True)
    communes_names = extract_individual_communes(project_name)

    avis_date_el = soup.select_one("time")
    avis_date = None
    if avis_date_el is not None:
        try:
            avis_date = datetime.strptime(avis_date_el.get("datetime"), "%Y-%m-%d")
        except Exception as exc:
            logger.debug(exc)

    pdf_url = soup.select_one("a.fr-download__link").get("href")
    pdf_filename = Path(pdf_url).name

    return get_scraped_avis_dict(
        project_name=project_name,
        communes_names=communes_names if len(communes_names) > 0 else None,
        departement_name=departement_name,
        project_date=avis_date,
        pdf_filename=pdf_filename,
        pdf_url=urljoin(url, pdf_url),
    )


def extract_individual_communes(communes_names_raw: str) -> list[str]:
    """Extract individual commune names from a raw project name string.

    Uses regex pattern matching to identify commune names in French format,
    supporting patterns like "commune de X", "communes de X et Y", with
    optional articles (la, le) and accented characters.

    Parameters
    ----------
    communes_names_raw : str
        Raw string containing commune information, typically a project name
        that includes commune references.

    Returns
    -------
    list[str]
        List of extracted commune names. Empty list if no communes are found.

    Examples
    --------
    >>> extract_individual_communes("Projet dans la commune de Montpellier")
    ['Montpellier']
    >>> extract_individual_communes("Communes de Béziers et Pézenas")
    ['Béziers', 'Pézenas']
    """
    communes_names = []

    match_o = re.search(
        r"(?:(?:commune de)|(?:communes de)) ((?:la |le )?[a-z\-éèùîûê]+) ?(?:(?:et)? ([a-z\-]+))?",
        communes_names_raw.replace("\xa0", " "),
        flags=re.I,
    )
    if match_o is not None:
        for i in range(1, match_o.lastindex + 1):
            communes_names.append(match_o.group(i))

    return communes_names


async def get_cas_par_cas_avis(client: AsyncClient) -> list[dict]:
    """Extract all avis metadata from the cas par cas archive section.

    Navigates through the cas par cas archive hierarchy: departements -> years ->
    listing pages -> avis pages. For each level, it uses concurrent requests
    with semaphore-controlled concurrency to efficiently gather all avis data.

    Parameters
    ----------
    client : httpx.AsyncClient
        The async HTTP client used for fetching page content.

    Returns
    -------
    list[dict]
        List of dictionaries containing avis metadata for all cas par cas
        entries across all departements and years.

    Notes
    -----
    This function orchestrates a multi-level scraping process:
    1. Fetches departement links from the main cas par cas page
    2. For each departement, fetches year-specific listing pages
    3. For each year, builds all listing page URLs (handling pagination)
    4. Extracts avis page URLs from each listing page
    5. Finally, extracts avis metadata from each avis page
    """
    soup = await get_soup_from_url(client, CAS_PAR_CAS_ARCHIVE_URL)

    departements_links = []
    for el in soup.select("a.lien-sous-rubrique.fr-link"):
        departements_links.append(
            {
                "departement_name": el.get_text(strip=True),
                "url": urljoin(CAS_PAR_CAS_ARCHIVE_URL, el.get("href")),
            }
        )

    sem = Semaphore(6)
    cas_par_cas_departement_year_first_page_links = await execute_coroutines(
        [
            get_cas_par_cas_departements_years_first_listing_page(
                client, e["url"], e["departement_name"], sem
            )
            for e in departements_links
        ],
        tqdm_desc="Occitanie Archive cas par cas - Getting department years urls",
    )

    all_listings_urls = await execute_coroutines(
        [
            get_all_cas_par_cas_listings_pages_urls(
                client, e["url"], e["departement_name"], e["year"], sem
            )
            for e in cas_par_cas_departement_year_first_page_links
        ],
        tqdm_desc="Occitanie Archive cas par cas - Getting all listings pages urls",
    )

    all_avis_pages_urls = await execute_coroutines(
        [
            get_all_cas_par_cas_avis_age(
                client, e["url"], e["departement_name"], e["year"], sem
            )
            for e in all_listings_urls
        ],
        tqdm_desc="Occitanie Archive cas par cas - Getting all avis pages",
    )

    all_cas_par_cas_avis = await execute_coroutines(
        [
            get_avis_from_cas_par_cas_page_url(
                client, e["url"], e["departement_name"], e["year"], sem
            )
            for e in all_avis_pages_urls
        ],
        tqdm_desc="Occitanie Archive cas par cas - Getting all avis",
        list_result=False,
    )

    return all_cas_par_cas_avis


async def get_cas_par_cas_departements_years_first_listing_page(
    client: AsyncClient, url: str, departement_name: str, semaphore: Semaphore
) -> list[dict]:
    """Extract year-specific listing page links from a departement's cas par cas page.

    Fetches the HTML content of a departement's cas par cas page and extracts
    all year-specific listing page links. Each link is paired with the
    departement name and the extracted year.

    Parameters
    ----------
    client : httpx.AsyncClient
        The async HTTP client used for fetching the page content.
    url : str
        URL of the departement's cas par cas page.
    departement_name : str
        Name of the departement (e.g., "Aude", "Gard", "Hérault").
    semaphore : asyncio.Semaphore
        Semaphore to control concurrency of HTTP requests.

    Returns
    -------
    list[dict]
        List of dictionaries containing year-specific listing page information.
        Each dictionary has keys "departement_name" (str), "year" (int), and
        "url" (str) pointing to the first listing page for that year.
    """
    async with semaphore:
        soup = await get_soup_from_url(client, url)

    departements_years_first_page_links = []
    for el in soup.select_one("div.liste-rubriques").select("a.fr-tile__link"):
        year = int(re.search(r"[0-9]{4}", el.get_text(strip=True)).group(0))
        el_url = el.get("href")
        departements_years_first_page_links.append(
            {
                "departement_name": departement_name,
                "year": year,
                "url": urljoin(url, el_url),
            }
        )

    return departements_years_first_page_links


async def get_all_cas_par_cas_listings_pages_urls(
    client: AsyncClient,
    url: str,
    departement_name: str,
    year: int,
    semaphore: Semaphore,
):
    """Build all listing page URLs for a given departement and year in cas par cas.

    Fetches the first listing page for a specific departement and year, then
    uses pagination parsing to construct URLs for all subsequent pages.

    Parameters
    ----------
    client : httpx.AsyncClient
        The async HTTP client used for fetching the page content.
    url : str
        URL of the first listing page for the given departement and year.
    departement_name : str
        Name of the departement (e.g., "Aude", "Gard", "Hérault").
    year : int
        Year of the avis listings (e.g., 2023, 2024).
    semaphore : asyncio.Semaphore
        Semaphore to control concurrency of HTTP requests.

    Returns
    -------
    list[dict]
        List of dictionaries containing listing page information. Each
        dictionary has keys "departement_name" (str), "year" (int), and
        "url" (str) pointing to individual listing pages.
    """
    async with semaphore:
        soup = await get_soup_from_url(client, url)

    listing_pages = build_listing_pages_urls(soup, url)

    return [
        {"departement_name": departement_name, "year": year, "url": e}
        for e in listing_pages
    ]


async def get_all_cas_par_cas_avis_age(
    client: AsyncClient,
    url: str,
    departement_name: str,
    year: int,
    semaphore: Semaphore,
) -> list[dict]:
    """Extract avis page URLs from a cas par cas listing page.

    Fetches the HTML content of a cas par cas listing page and extracts
    all avis page links. Each link is filtered through the project_filter
    function to ensure relevance.

    Parameters
    ----------
    client : httpx.AsyncClient
        The async HTTP client used for fetching the page content.
    url : str
        URL of the cas par cas listing page.
    departement_name : str
        Name of the departement (e.g., "Aude", "Gard", "Hérault").
    year : int
        Year of the avis listings (e.g., 2023, 2024).
    semaphore : asyncio.Semaphore
        Semaphore to control concurrency of HTTP requests.

    Returns
    -------
    list[dict]
        List of dictionaries containing avis page information. Each
        dictionary has keys "departement_name" (str), "year" (int), and
        "url" (str) pointing to individual avis pages.
    """
    async with semaphore:
        soup = await get_soup_from_url(client, url)

    avis_page_urls = []
    for el in soup.select("a.fr-card__link.article-card-lien"):
        project_name = el.get_text(strip=True)
        if not project_filter(project_name):
            continue

        project_url = el.get("href")

        avis_page_urls.append(
            {
                "departement_name": departement_name,
                "year": year,
                "url": urljoin(CAS_PAR_CAS_ARCHIVE_URL, project_url),
            }
        )

    return avis_page_urls


async def get_avis_from_cas_par_cas_page_url(
    client: AsyncClient,
    url: str,
    departement_name: str,
    year: int,
    semaphore: Semaphore,
) -> dict:
    """Extract avis metadata from an individual cas par cas avis page.

    Fetches the HTML content of a cas par cas avis page and extracts the
    project name, commune names, avis date, and PDF document URL. The commune
    names are extracted from the project name using pattern matching. If the
    avis date cannot be parsed from the page, it defaults to January 1st of
    the given year.

    Parameters
    ----------
    client : httpx.AsyncClient
        The async HTTP client used for fetching the page content.
    url : str
        URL of the individual cas par cas avis page.
    departement_name : str
        Name of the departement to which this avis belongs.
    year : int
        Year of the avis (used as fallback if date parsing fails).
    semaphore : asyncio.Semaphore
        Semaphore to control concurrency of HTTP requests.

    Returns
    -------
    dict
        Dictionary containing avis metadata with keys: "project_name",
        "communes_names", "departement_name", "project_date", "pdf_filename",
        and "pdf_url".
    """
    async with semaphore:
        soup = await get_soup_from_url(client, url)

    project_name = soup.select_one("h1.titre-article").get_text(strip=True)
    communes_names = extract_individual_communes(project_name)

    avis_date_el = soup.select_one("time")
    avis_date = None
    if avis_date_el is not None:
        try:
            avis_date = datetime.strptime(avis_date_el.get("datetime"), "%Y-%m-%d")
        except Exception as exc:
            logger.debug(exc)
            avis_date = datetime(year, 1, 1)

    pdf_url = soup.select("a.fr-download__link")[-1].get("href")
    pdf_filename = Path(pdf_url).name

    return get_scraped_avis_dict(
        project_name=project_name,
        communes_names=communes_names if len(communes_names) > 0 else None,
        departement_name=departement_name,
        project_date=avis_date,
        pdf_filename=pdf_filename,
        pdf_url=urljoin(url, pdf_url),
    )


if __name__ == "__main__":
    asyncio.run(get_occitanie_archive_pdf_urls_and_metadata())
