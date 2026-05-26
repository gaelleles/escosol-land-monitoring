"""
Module containing utilities to scrape ex-Aquitaine, ex-Limousin, ex-Poitou-Charentes AE archive website
(https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/archives-ex-aquitaine-ex-limousin-ex-poitou-r3920.html)
and extract relevant AE metadata and PDFs.
"""

import asyncio
import locale
import logging
import math
import random
import re
import time
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
import pandas as pd
from bs4 import BeautifulSoup
from bs4.element import Tag
from tqdm import tqdm
from tqdm.asyncio import tqdm_asyncio
from tqdm.contrib.logging import logging_redirect_tqdm

from ..config import (
    get_http_client,
    project_filter,
)
from ..utils.data import get_scraped_avis_dict
from ..utils.scraping import get_soup_from_url

locale.setlocale(locale.LC_ALL, "fr_FR.UTF-8")

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)

BASE_URL = "https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/"
ARCHIVE_URL = "https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/archives-ex-aquitaine-ex-limousin-ex-poitou-r3920.html"


#########################################################################
#                                                                       #
#   Scraping site with following hierarchical organization:             #
#   departement page -> communes page with pagination -> commune page    #
#                                                                       #
#########################################################################
async def aquitaine_departemental_scraping(url: str) -> pd.DataFrame:
    """
    Scrape the Aquitaine departemental archive page to extract avis metadata.

    Navigates through departement pages, extracts commune page URLs with pagination,
    and collects avis data from each commune page.

    Parameters
    ----------
    url : str
        The URL of the Aquitaine departemental archive page.

    Returns
    -------
    pd.DataFrame
        DataFrame containing extracted avis with metadata.
    """
    avis = []
    async with get_http_client() as client:
        soup = await get_soup_from_url(client, url)

        # Get all departements communes first page urls
        departements_links = {}
        departements_links_elements = soup.find_all("a", class_="fr-tile__link")
        for e in departements_links_elements:
            departement_name = e.get_text()
            if (
                departement_name
                == "Région Aquitaine (projets sur plusieurs départements)"
            ):
                continue  # No projects in this page

            departement_communes_first_page_url = urljoin(ARCHIVE_URL, e.get("href"))
            departements_links[departement_name] = departement_communes_first_page_url

        # Get all departement communes pages
        departement_communes_pages_urls = (
            await get_all_departements_communes_pages_urls(client, departements_links)
        )

        # Extract all communes pages urls
        communes_pages_urls = await get_all_communes_pages_urls(
            client, departement_communes_pages_urls, "fr-card__link article-card-lien"
        )

        # Extract all avis by scraping all communes pages from all departements
        avis = await get_all_avis_from_communes_pages(client, communes_pages_urls)

    return pd.DataFrame(avis)


async def get_all_departements_communes_pages_urls(
    client: httpx.AsyncClient, departements_links: dict
) -> list[dict]:
    """
    Collects all departement communes page URLs concurrently.

    Iterates over provided departement links, fetches each page, and extracts
    pagination URLs for communes listings.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    departements_links : dict
        Dictionary mapping departement names to their first-page URLs.

    Returns
    -------
    list[dict]
        List of dictionaries containing departement names and corresponding URLs.
    """
    departement_commune_pages_urls = []
    coroutines = []
    sem = asyncio.Semaphore(4)
    for (
        departement_name,
        departement_communes_first_page_url,
    ) in departements_links.items():
        coroutines.append(
            extract_all_departement_commune_pages_from_departement_page(
                client, departement_communes_first_page_url, departement_name, sem
            )
        )
    coroutines_res = await tqdm_asyncio.gather(
        *coroutines,
        desc="Archive - Getting all departements communes pages links",
    )
    for res in coroutines_res:
        departement_commune_pages_urls.extend(res)

    return departement_commune_pages_urls


async def extract_all_departement_commune_pages_from_departement_page(
    client: httpx.AsyncClient,
    departement_communes_first_page_url: str,
    departement_name: str,
    sempaphore: asyncio.Semaphore,
) -> list[dict[str, str]]:
    """
    Extracts all pagination URLs for a specific departement's commune pages.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    departement_communes_first_page_url : str
        The URL of the first page of commune listings for the departement.
    departement_name : str
        The name of the departement.
    sempaphore : asyncio.Semaphore
        Semaphore for rate limiting concurrent requests.

    Returns
    -------
    list[dict[str, str]]
        List of dictionaries containing the departement name and the URL for each page.
    """
    async with sempaphore:
        soup = await get_soup_from_url(client, departement_communes_first_page_url)
    urls = build_departement_commune_pages_urls(
        soup, departement_communes_first_page_url
    )
    res = [{"departement_name": departement_name, "url": e} for e in urls]
    await asyncio.sleep(random.uniform(0.3, 1.8))
    return res


def build_departement_commune_pages_urls(
    soup: BeautifulSoup, first_page_url: str
) -> list[str]:
    """
    Builds a list of URLs for all pages of a departement's commune listings.

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
    urls = [urljoin(BASE_URL, first_page_url)]

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
    step = math.ceil(last_offset / last_page_number)

    for offset in range(step, last_offset + step, step):
        urls.append(
            urljoin(
                BASE_URL,
                re.sub(
                    r"debut_listearticles=[0-9]+",
                    f"debut_listearticles={offset}",
                    last_page_url,
                ),
            )
        )

    return urls


async def get_all_communes_pages_urls(
    client: httpx.AsyncClient,
    departement_commune_pages_urls: list[dict],
    class_name: str | None = None,
) -> list[dict]:
    """
    Collects URLs for all commune pages from the provided departement pages concurrently.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    departement_commune_pages_urls : list[dict]
        List of dictionaries containing departement and page information.
    class_name : str, optional
        CSS class name used to identify links to commune pages. Default is None.

    Returns
    -------
    list[dict]
        List of dictionaries containing commune names and their corresponding URLs.
    """
    commune_pages_urls = []
    coroutines = []
    sem = asyncio.Semaphore(6)
    for e in departement_commune_pages_urls:
        coroutines.append(
            get_communes_urls_from_communes_page(
                client, e["url"], e["departement_name"], class_name, sem
            )
        )
    coroutines_res = await tqdm_asyncio.gather(
        *coroutines,
        desc="Archive - Getting all communes links",
    )
    for res in coroutines_res:
        commune_pages_urls.extend(res)

    return commune_pages_urls


async def get_communes_urls_from_communes_page(
    client: httpx.AsyncClient,
    departement_commune_page_url: str,
    departement_name: str,
    class_name: str | None,
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    """
    Extracts links to commune pages from a specific departement page.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    departement_commune_page_url : str
        The URL of the departement page to scrape.
    departement_name : str
        The name of the departement.
    class_name : str, optional
        CSS class name used to identify links to commune pages.
    semaphore : asyncio.Semaphore
        Semaphore for rate limiting.

    Returns
    -------
    list[dict]
        List of dictionaries containing commune names and URLs.
    """
    async with semaphore:
        soup = await get_soup_from_url(client, departement_commune_page_url)

    links = extract_all_communes_links_in_page(soup, class_name)
    links = [{**e, "departement_name": departement_name} for e in links]
    await asyncio.sleep(random.uniform(0.8, 3.7))
    return links


async def get_all_avis_from_communes_pages(
    client: httpx.AsyncClient, communes_pages_urls: list[dict[str, Any]]
):
    """
    Collects avis data from all provided commune pages concurrently.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    communes_pages_urls : list[dict[str, Any]]
        List of dictionaries containing commune and page information.

    Returns
    -------
    list[dict]
        List of dictionaries containing avis metadata.
    """
    avis = []
    coroutines = []
    sem = asyncio.Semaphore(6)
    for e in communes_pages_urls:
        coroutines.append(
            get_avis_from_commune_url(
                client, e["url"], e["commune_name"], e["departement_name"], sem
            )
        )
    coroutines_res = await tqdm_asyncio.gather(
        *coroutines,
        desc="Nouvelle Aquitaine - Getting all communes links",
    )
    for res in coroutines_res:
        avis.extend(res)

    return avis


async def get_avis_from_commune_url(
    client: httpx.AsyncClient,
    commune_url: str,
    commune_name: str,
    departement_name: str,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """
    Scrapes avis data from a specific commune page.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    commune_url : str
        The URL of the commune page.
    commune_name : str
        The name of the commune.
    departement_name : str
        The name of the departement.
    semaphore : asyncio.Semaphore
        Semaphore for rate limiting.

    Returns
    -------
    list[dict[str, Any]]
        List of dictionaries containing avis metadata.
    """
    avis = []

    async with semaphore:
        res = await client.get(urljoin(BASE_URL, commune_url))
    if res.status_code == 503:
        logger.debug("Failed retry strategy, making a manual blocking retry...")
        time.sleep(30)
        res = await client.get(urljoin(BASE_URL, commune_url))

    soup = BeautifulSoup(res.text, "html.parser")

    li_elements = soup.find("div", class_="contenu-article").find_all("li")

    for e in li_elements:
        name_e = e.find("strong")
        if name_e is None:
            continue
        name = name_e.get_text()

        if not project_filter(name.lower()):
            continue

        project_name = name
        raw_date = None
        if "Publié" in name:
            project_name, raw_date = name.split("—")

        project_date = None
        if raw_date is not None:
            try:
                project_date = datetime.strptime(raw_date.strip(), "Publié en %B %Y")
            except Exception as exc:
                print(exc)

        pdf_url = e.find("a", class_="fr-download__link").get("href")
        pdf_name = Path(pdf_url).name

        avis.append(
            get_scraped_avis_dict(
                project_name=project_name.strip(),
                communes_names=[commune_name],
                departement_name=departement_name,
                project_date=project_date,
                pdf_filename=pdf_name,
                pdf_url=urljoin(BASE_URL, pdf_url),
            )
        )

    await asyncio.sleep(random.uniform(1.2, 8))
    return avis


def extract_all_communes_links_in_page(
    soup: BeautifulSoup, class_name: str | None = "fr-card__link article-card-lien"
) -> list[dict[str, str]]:
    """
    Extracts links to commune pages from a BeautifulSoup object.

    Parameters
    ----------
    soup : BeautifulSoup
        The parsed HTML content of the page.
    class_name : str, optional
        CSS class name used to identify links. Default is "fr-card__link article-card-lien".

    Returns
    -------
    list[dict[str, str]]
        List of dictionaries containing commune names and URLs.
    """
    communes_links = []
    communes_links_elements = soup.find_all("a", class_=class_name)
    for e in communes_links_elements:
        commune_name = e.get_text()

        commune_url = urljoin(ARCHIVE_URL, e.get("href"))
        communes_links.append({"commune_name": commune_name, "url": commune_url})

    return communes_links


#########################################################################
#                                                                       #
#   Scraping site with following hierarchical organization:             #
#   departement page -> A-Z communes page with pagination               #
#   -> communes page table -> commune page                              #
#                                                                       #
#########################################################################


async def poitou_charentes_departemental_scraping(url: str) -> pd.DataFrame:
    """
    Scrape the Poitou-Charentes departemental archive page to extract avis metadata.

    Navigates through departement pages, extracts commune page URLs with pagination,
    and collects avis data from each commune page.

    Parameters
    ----------
    url : str
        The URL of the Poitou-Charentes departemental archive page.

    Returns
    -------
    pd.DataFrame
        DataFrame containing extracted avis with metadata.
    """
    avis = []

    async with get_http_client() as client:
        soup = await get_soup_from_url(client, url)

        # Get all departements communes first page urls
        departements_links = {}
        departements_links_elements = soup.find_all("a", class_="fr-tile__link")
        for e in departements_links_elements:
            departement_name = e.get_text(strip=True)
            if departement_name == "Région Poitou-Charentes":
                continue  # No projects in this page

            departement_communes_first_page_url = urljoin(ARCHIVE_URL, e.get("href"))
            departements_links[departement_name] = departement_communes_first_page_url

        # Get all departement communes pages
        departement_communes_pages_urls = (
            await get_all_departements_communes_pages_urls(client, departements_links)
        )

        # Extract all communes pages urls
        communes_pages_urls = await get_all_communes_pages_urls(
            client, departement_communes_pages_urls, "fr-card__link article-card-lien"
        )
        #
        communes_pages_urls = [
            e
            for e in communes_pages_urls
            if re.match(r"Communes [A_Z]…", e["commune_name"]) is None
        ]

        # Extract all avis from all commune pages
        avis = await get_all_avis_from_commune_pages(client, communes_pages_urls)

    return pd.DataFrame(avis)


async def get_all_avis_from_commune_pages(
    client: httpx.AsyncClient, communes_pages_urls: list[dict]
) -> list[dict[str, Any]]:
    """
    Collects avis data from all provided commune pages concurrently.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    communes_pages_urls : list[dict]
        List of dictionaries containing commune and page information.

    Returns
    -------
    list[dict[str, Any]]
        List of dictionaries containing avis metadata.
    """
    avis = []
    coroutines = []
    sem = asyncio.Semaphore(6)
    for e in communes_pages_urls:
        coroutines.append(
            get_avis_from_commune_page_url(
                client, e["url"], e["commune_name"], e["departement_name"], sem
            )
        )
    coroutines_res = await tqdm_asyncio.gather(
        *coroutines,
        desc="Archive - Getting all avis",
    )
    for res in coroutines_res:
        avis.extend(res)

    return avis


async def get_avis_from_commune_page_url(
    client: httpx.AsyncClient,
    commune_page_url: str,
    commune_name: str,
    departement_name: str,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """
    Scrapes avis data from a specific commune page.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    commune_page_url : str
        The URL of the commune page.
    commune_name : str
        The name of the commune.
    departement_name : str
        The name of the departement.
    semaphore : asyncio.Semaphore
        Semaphore for rate limiting.

    Returns
    -------
    list[dict[str, Any]]
        List of dictionaries containing avis metadata.
    """
    async with semaphore:
        soup = await get_soup_from_url(client, commune_page_url)

    avis = extract_all_avis_from_commune_page(soup, commune_name, departement_name)
    await asyncio.sleep(random.uniform(2, 5))

    return avis


def extract_all_avis_from_commune_page(
    soup: BeautifulSoup, commune_name: str, departement_name: str
) -> list[dict[str, Any]]:
    """
    Extracts avis data from the HTML content of a commune page.

    Parameters
    ----------
    soup : BeautifulSoup
        The parsed HTML content of the commune page.
    commune_name : str
        The name of the commune.
    departement_name : str
        The name of the departement.

    Returns
    -------
    list[dict[str, Any]]
        List of dictionaries containing avis metadata.
    """
    avis = []

    li_elements = soup.find("div", class_="contenu-article").find_all("li")
    for li_e in li_elements:
        if (len(li_e.contents) < 2) or (li_e.contents[1].name == "strong"):
            continue  # It's the outer list element, we want only the inner ones
        li_text = li_e.get_text()
        if not project_filter(li_text.lower()):
            continue

        project_name = ""
        i = 0
        while not project_filter(project_name.lower()):
            temp = li_e.contents[i]
            if isinstance(temp, str):
                project_name += temp
            else:
                project_name += temp.get_text()
            i += 1

        a_element = li_e.find("a")

        if a_element is None:
            continue

        pdf_url = a_element.get("href")
        pdf_name = Path(pdf_url).name

        project_date = None
        raw_date = a_element.get_text()
        try:
            project_date = datetime.strptime(raw_date.strip(), "%d %B %Y")
        except Exception as ex:
            logger.debug(ex)

        avis.append(
            get_scraped_avis_dict(
                project_name=project_name.strip(),
                communes_names=[commune_name],
                departement_name=departement_name,
                project_date=project_date,
                pdf_filename=pdf_name,
                pdf_url=urljoin(BASE_URL, pdf_url),
            )
        )

    return avis


#########################################################################
#                                                                       #
#   Scraping site with following hierarchical organization:             #
#   departement page -> years page -> avis pages                        #
#                                                                       #
#########################################################################


async def poitou_charentes_departemental_yearly_scraping(url: str) -> pd.DataFrame:
    """
    Scrape the Poitou-Charentes departemental archive page using the yearly organization.

    Navigates through departement pages, extracts year links, and collects avis data
    from each year's page.

    Parameters
    ----------
    url : str
        The URL of the Poitou-Charentes departemental archive page.

    Returns
    -------
    pd.DataFrame
        DataFrame containing extracted avis with metadata.
    """
    avis = []

    async with get_http_client() as client:
        soup = await get_soup_from_url(client, url)

        departements_links = {}
        departements_links_elements = soup.find_all("a", class_="fr-tile__link")
        for e in departements_links_elements:
            departement_name = e.get_text()

            departement_url = urljoin(ARCHIVE_URL, e.get("href"))
            departements_links[departement_name] = departement_url

        # Get all departements years links:
        departements_years_links = await get_departements_years_links(
            client, departements_links
        )

        # Extract all avis
        avis = await get_all_avis_from_departements_years_pages(
            client, departements_years_links
        )

    return pd.DataFrame(avis)


async def get_departements_years_links(
    client: httpx.AsyncClient, departements_links: dict
) -> list[dict]:
    """
    Collects year links for each departement concurrently.

    Iterates over provided departement links, fetches each page, and extracts
    pagination links for years.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    departements_links : dict
        Dictionary mapping departement names to their URLs.

    Returns
    -------
    list[dict]
        List of dictionaries containing departement names and corresponding year links.
    """
    departements_years_links = []
    coroutines = []
    sem = asyncio.Semaphore(6)
    for departement_name, url in departements_links.items():
        coroutines.append(
            get_departement_years_links(client, url, departement_name, sem)
        )
    coroutines_res = await tqdm_asyncio.gather(
        *coroutines,
        desc="Archive - Getting all departements years links",
    )
    for res in coroutines_res:
        departements_years_links.extend(res)

    return departements_years_links


async def get_departement_years_links(
    client: httpx.AsyncClient,
    departement_url: str,
    departement_name: str,
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    """
    Fetches and extracts year links from a single departement page.

    Retrieves the HTML content of the provided departement URL, extracts links
    to yearly archive pages, and associates them with the departement name.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    departement_url : str
        The URL of the departement page to scrape.
    departement_name : str
        The name of the departement.
    semaphore : asyncio.Semaphore
        Semaphore for rate limiting concurrent requests.

    Returns
    -------
    list[dict]
        List of dictionaries containing the departement name, year, and URL
        for each yearly archive page found on the departement page.
    """

    async with semaphore:
        soup = await get_soup_from_url(client, departement_url)

    years_links = [
        {"departement_name": departement_name, **e}
        for e in extract_departements_years_links(soup)
    ]

    await asyncio.sleep(random.uniform(0.3, 1.9))
    return years_links


def extract_departements_years_links(soup: BeautifulSoup) -> list[dict]:
    """
    Extracts links to yearly archive pages from a departement page.

    Parses the HTML content to find anchor elements with the class
    "fr-card__link article-card-lien", extracts the year from the title
    attribute, and constructs the full URL for each year link.

    Parameters
    ----------
    soup : BeautifulSoup
        The parsed HTML content of the departement page.

    Returns
    -------
    list[dict]
        List of dictionaries containing the year (as an integer) and the
        full URL for each yearly archive page.
    """
    years_links = []
    year_a_elements = soup.find_all("a", class_="fr-card__link article-card-lien")

    for year_a_e in year_a_elements:
        year_raw = year_a_e.get("title")
        year = int(year_raw.replace("En ", ""))

        years_links.append(
            {"year": year, "url": urljoin(BASE_URL, year_a_e.get("href"))}
        )

    return years_links


async def get_all_avis_from_departements_years_pages(
    client: httpx.AsyncClient, departements_years_links: list[dict]
) -> list[dict[str, Any]]:
    """
    Collects avis data from all departement year pages concurrently.

    Iterates over the provided list of departement-year links, fetches avis
    data from each year page, and aggregates the results.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    departements_years_links : list[dict]
        List of dictionaries containing departement names, years, and
        corresponding URLs for yearly archive pages.

    Returns
    -------
    list[dict[str, Any]]
        List of dictionaries containing avis metadata extracted from all
        departement year pages.
    """
    avis = []
    coroutines = []
    sem = asyncio.Semaphore(6)
    for e in departements_years_links:
        coroutines.append(
            get_all_avis_from_departement_year_page(
                client, e["url"], e["departement_name"], e["year"], sem
            )
        )
    coroutines_res = await tqdm_asyncio.gather(
        *coroutines,
        desc="Archive - Getting all avis",
    )
    for res in coroutines_res:
        avis.extend(res)

    return avis


async def get_all_avis_from_departement_year_page(
    client: httpx.AsyncClient,
    departement_year_page_url: str,
    departement_name: str,
    year: int,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """
    Scrapes avis data from a specific departement year page.

    Fetches the HTML content of the given year page, extracts avis metadata
    from the table rows, and applies rate limiting via semaphore.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    departement_year_page_url : str
        The URL of the departement year page to scrape.
    departement_name : str
        The name of the departement.
    year : int
        The year associated with this archive page.
    semaphore : asyncio.Semaphore
        Semaphore for rate limiting concurrent requests.

    Returns
    -------
    list[dict[str, Any]]
        List of dictionaries containing avis metadata extracted from the
        departement year page.
    """
    async with semaphore:
        soup = await get_soup_from_url(client, departement_year_page_url)

    avis = extract_avis_from_departement_year_page(soup, departement_name, year)

    await asyncio.sleep(random.uniform(0.3, 1.9))
    return avis


def extract_avis_from_departement_year_page(
    soup: BeautifulSoup, departement_name: str, year: int
) -> list[dict[str, Any]]:
    """
    Extracts avis data from the HTML content of a departement year page.

    Parses table rows to identify commune names and avis entries. Filters
    projects based on relevance criteria, extracts PDF URLs, and parses
    publication dates. Falls back to January 1st of the given year if
    date parsing fails.

    Parameters
    ----------
    soup : BeautifulSoup
        The parsed HTML content of the departement year page.
    departement_name : str
        The name of the departement.
    year : int
        The year associated with this archive page, used as fallback
        for date parsing failures.

    Returns
    -------
    list[dict[str, Any]]
        List of dictionaries containing avis metadata including project
        name, commune names, departement name, project date, PDF filename,
        and PDF URL.
    """
    avis = []

    table_rows_commune_elements = soup.find_all("tr")
    communes_names = None
    for row_e in table_rows_commune_elements[1:]:
        if len(row_e.contents) == 0:
            continue

        if row_e.get("class") == "row_even even":
            communes_names = re.split(r" - | / ", row_e.get_text(strip=True))
            continue

        table_elements = row_e.find_all("td")

        project_name = table_elements[0].get_text()
        if not project_filter(project_name.lower()):
            continue

        link_e = table_elements[1].find("a")
        if link_e is None:
            continue

        pdf_url = link_e.get("href")
        pdf_name = Path(pdf_url).name

        project_date = None
        raw_date = link_e.get("title")
        try:
            project_date = datetime.strptime(raw_date.strip(), "%d %B %Y")
        except Exception as ex:
            project_date = datetime(year, 1, 1)
            logger.debug(ex)

        avis.append(
            get_scraped_avis_dict(
                project_name=project_name.strip(),
                communes_names=communes_names,
                departement_name=departement_name,
                project_date=project_date,
                pdf_filename=pdf_name,
                pdf_url=urljoin(BASE_URL, pdf_url),
            )
        )

    return avis


#########################################################################
#                                                                       #
#   Scraping Limousin projects (only one page)                          #
#                                                                       #
#########################################################################


async def limousin_project_table_scraping(url: str) -> pd.DataFrame:
    """
    Scrape the Limousin projects page containing project tables.

    Extracts avis data from the single-page layout containing departement sections
    and HTML tables with project information.

    Parameters
    ----------
    url : str
        The URL of the Limousin projects page.

    Returns
    -------
    pd.DataFrame
        DataFrame containing extracted avis with metadata.
    """
    avis = []

    async with get_http_client() as client:
        soup = await get_soup_from_url(client, url)

        departements_elements = soup.select("div.texte-article.fr-text")[0].select(
            "h2:has(font)"
        )[1:]

        for departement_e in departements_elements:
            departement_name = departement_e.get_text()

            next_sibling_e = departement_e.next_sibling

            year = None
            while (next_sibling_e is not None) and (not next_sibling_e.name == "h2"):
                if next_sibling_e.name == "p":
                    year = next_sibling_e.get_text().replace("-", "").strip()
                elif next_sibling_e.name == "table":
                    avis_tmp = extract_avis_from_table(next_sibling_e)

                    avis_tmp = [
                        get_scraped_avis_dict(
                            project_name=e["project_name"],
                            communes_names=e["communes_names"],
                            departement_name=departement_name,
                            project_date=e["date_scraped"],
                            pdf_filename=e["pdf_filename"],
                            pdf_url=e["pdf_url"],
                        )
                        for e in avis_tmp
                    ]
                    avis.extend(avis_tmp)

                next_sibling_e = next_sibling_e.next_sibling

    return pd.DataFrame(avis)


def extract_avis_from_table(table_element: Tag) -> list[dict[str, Any]]:
    """
    Extracts avis data from an HTML table element.

    Iterates over table body rows, extracts project names, commune names,
    PDF URLs, and publication dates. Filters projects based on relevance
    criteria.

    Parameters
    ----------
    table_element : Tag
        The BeautifulSoup Tag representing the HTML table element.

    Returns
    -------
    list[dict[str, Any]]
        List of dictionaries containing avis metadata with keys:
        - project_name : str
            Name of the project.
        - communes_names : list[str]
            List of commune names associated with the project.
        - date_scraped : datetime
            Publication date of the avis.
        - pdf_url : str
            Full URL to the PDF document.
        - pdf_filename : str
            Filename of the PDF document.
    """
    avis = []

    table_body_e: Tag = table_element.find("tbody")

    for row_e in table_body_e.children:
        if row_e == "\n":
            continue

        content_clean = [e for e in row_e.contents if e != "\n"]

        project_cell_e = content_clean[1]
        project_name = project_cell_e.get_text()

        if not project_filter(project_name):
            continue

        communes_names = content_clean[3].get_text(strip=True).split(", ")

        avis_e = content_clean[6].find("a")
        if avis_e is None:
            continue

        pdf_url = avis_e.get("href")
        pdf_filename = Path(pdf_url).name
        avis_date = datetime.strptime(avis_e.get_text().strip(), "%d/%m/%Y")

        avis.append(
            {
                "project_name": project_name,
                "communes_names": communes_names,
                "date_scraped": avis_date,
                "pdf_url": urljoin(BASE_URL, pdf_url),
                "pdf_filename": pdf_filename,
            }
        )

    return avis


#########################################################################
#                                                                       #
#   Scraping site with following hierarchical organization:             #
#   departement page -> communes list page -> avis pages                #
#                                                                       #
#########################################################################


async def departemental_scraping(url: str) -> pd.DataFrame:
    """
    Scrape the departemental archive page with commune list organization.

    Navigates through departement pages, extracts commune list pages, and collects
    avis data from each commune's table page.

    Parameters
    ----------
    url : str
        The URL of the departemental archive page.

    Returns
    -------
    pd.DataFrame
        DataFrame containing extracted avis with metadata.
    """
    avis = []

    async with get_http_client() as client:
        soup = await get_soup_from_url(client, url)

        departements_links = []
        departements_links_elements = soup.find_all(
            "a", class_="fr-card__link article-card-lien"
        )
        for e in departements_links_elements:
            departement_name = e.get_text(strip=True)
            departement_url = urljoin(ARCHIVE_URL, e.get("href"))
            departements_links.append(
                {"departement_name": departement_name, "url": departement_url}
            )

        commune_links = await get_all_communes_pages_urls(
            client, departements_links, "spip_in"
        )

        avis = await get_all_avis_from_communes_table_pages(client, commune_links)

    return pd.DataFrame(avis)


async def get_all_avis_from_communes_table_pages(
    client: httpx.AsyncClient, commune_links: list[dict]
) -> list[dict]:
    """
    Collects avis data from all commune table pages concurrently.

    Iterates over the provided list of commune links, fetches avis data
    from each commune's table page, and aggregates the results.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    commune_links : list[dict]
        List of dictionaries containing commune names, departement names,
        and corresponding URLs for commune table pages.

    Returns
    -------
    list[dict]
        List of dictionaries containing avis metadata extracted from all
        commune table pages.
    """
    avis = []
    coroutines = []
    sem = asyncio.Semaphore(6)
    for e in commune_links:
        coroutines.append(
            get_all_avis_in_table_from_commune_url(
                client, e["url"], e["commune_name"], e["departement_name"], sem
            )
        )
    coroutines_res = await tqdm_asyncio.gather(
        *coroutines,
        desc="Archive - Getting all avis",
    )
    for res in coroutines_res:
        avis.extend(res)

    return avis


async def get_all_avis_in_table_from_commune_url(
    client: httpx.AsyncClient,
    commune_url: str,
    commune_name: str,
    departement_name: str,
    semaphore: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    """
    Scrapes avis data from a specific commune table page.

    Fetches the HTML content of the given commune URL, extracts avis
    metadata from the table rows, and applies rate limiting via semaphore.

    Parameters
    ----------
    client : httpx.AsyncClient
        Async HTTP client instance.
    commune_url : str
        The URL of the commune table page to scrape.
    commune_name : str
        The name of the commune.
    departement_name : str
        The name of the departement.
    semaphore : asyncio.Semaphore
        Semaphore for rate limiting concurrent requests.

    Returns
    -------
    list[dict[str, Any]]
        List of dictionaries containing avis metadata extracted from the
        commune table page.
    """
    async with semaphore:
        soup = await get_soup_from_url(client, commune_url)
    avis = extract_avis_from_commune_table_page(soup, commune_name, departement_name)
    await asyncio.sleep(random.uniform(1.2, 5))
    return avis


def extract_avis_from_commune_table_page(
    soup: BeautifulSoup, commune_name: str, departement_name: str
) -> list[dict[str, Any]]:
    """
    Extracts avis data from the HTML content of a commune table page.

    Parses table rows to find links with class "spip_in", extracts project
    names, PDF URLs, and publication dates. Filters projects based on
    relevance criteria.

    Parameters
    ----------
    soup : BeautifulSoup
        The parsed HTML content of the commune table page.
    commune_name : str
        The name of the commune.
    departement_name : str
        The name of the departement.

    Returns
    -------
    list[dict[str, Any]]
        List of dictionaries containing avis metadata including project
        name, commune names, departement name, project date, PDF filename,
        and PDF URL.
    """
    avis = []
    row_elements = soup.find_all("tr")
    for row_e in row_elements:
        link_e = row_e.find("a", class_="spip_in")
        if link_e is None:
            continue

        project_name = row_e.contents[1].get_text(strip=True)

        if not project_filter(project_name):
            continue

        pdf_url = link_e.get("href")
        pdf_filename = Path(pdf_url).name

        avis_date_raw = link_e.get_text()
        avis_date = None
        try:
            avis_date = datetime.strptime(avis_date_raw, "%d/%m/%Y")
        except Exception as e:
            logger.debug(e)

        avis.append(
            get_scraped_avis_dict(
                project_name=project_name,
                communes_names=[commune_name],
                departement_name=departement_name,
                project_date=avis_date,
                pdf_filename=pdf_filename,
                pdf_url=urljoin(BASE_URL, pdf_url),
            )
        )

    return avis


ARCHIVES_URLS_SCRAPPING_MAP = {
    "https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/projets-avis-de-l-autorite-environnementale-en-r4793.html": aquitaine_departemental_scraping,
    "https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/projets-examen-au-cas-par-cas-decisions-avant-le-r4794.html": aquitaine_departemental_scraping,
    "https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/avis-de-l-autorite-environnementale-en-poitou-r3699.html": poitou_charentes_departemental_scraping,
    "https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/examen-au-cas-par-cas-projets-demandes-decisions-r3913.html": poitou_charentes_departemental_yearly_scraping,
    "https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/les-avis-de-l-autorite-environnementale-en-a3831.html": limousin_project_table_scraping,
    "https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/projets-avis-de-l-autorite-environnementale-a-r1018.html": departemental_scraping,
    "https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/projets-examen-au-cas-par-cas-demandes-decisions-a-r1020.html": departemental_scraping,
}


async def get_nouvelle_aquitaine_archive_pdf_urls_and_metadata() -> pd.DataFrame:
    """Extract AE PDF links and metadata from ex-Aquitaine, ex-Limousin, ex-Poitou-Charentes AE
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
    >>> df = asyncio.run(get_nouvelle_aquitaine_archive_pdf_urls_and_metadata())
    """

    avis_dfs = []

    for url, func in tqdm(
        ARCHIVES_URLS_SCRAPPING_MAP.items(),
        desc="Scraping Nouvelle-Aquitaine archive websites",
    ):
        df = await func(url)
        avis_dfs.append(df)

    full_df = pd.concat(avis_dfs)

    return full_df


if __name__ == "__main__":
    with logging_redirect_tqdm():
        # asyncio.run(get_nouvelle_aquitaine_archive_pdf_urls_and_metadata())
        asyncio.run(get_nouvelle_aquitaine_archive_pdf_urls_and_metadata())
