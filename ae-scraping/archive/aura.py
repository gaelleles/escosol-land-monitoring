"""
Module containing utilities to scrape Auvergne Rhone Alpes archive website
(https://www.nouvelle-aquitaine.developpement-durable.gouv.fr/archives-ex-aquitaine-ex-limousin-ex-poitou-r3920.html)
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

PROJECTS_ARCHIVE_URL = (
    "https://www.auvergne-rhone-alpes.developpement-durable.gouv.fr/projets-r3548.html"
)
CAS_PAR_CAS_ARCHIVE_URL = (
    "https://www.auvergne-rhone-alpes.developpement-durable.gouv.fr/energie-r4075.html"
)

OLD_AVIS_DEPARTEMENTS = [
    "Ain (01)",
    "Ardèche (07)",
    "Drôme (26)",
    "Isère (38)",
    "Loire (42)",
    "Rhône (69)",
    "Savoie (73)",
    "Haute-Savoie (74)",
]


async def get_aura_archive_pdf_urls_and_metadata() -> pd.DataFrame:
    """Extract AE PDF links and metadata from Auvergne Rhone Alpes AE
    archive website.

    Scrapes the archives to find relevant AEs,
    extracting project names, commune information, departement details, and
    associated PDF document URLs.

    Returns
    -------
    pd.DataFrame
        DataFrame containing extracted avis.

    Examples
    --------
    >>> import asyncio
    >>> df = asyncio.run(get_aura_archive_pdf_urls_and_metadata())
    """
    avis = []

    async with get_http_client() as client:
        cas_par_cas_avis = await get_all_cas_par_cas_avis(client)
        avis.extend(cas_par_cas_avis)

        departements_page_soup = await get_soup_from_url(client, PROJECTS_ARCHIVE_URL)
        departements_links_elements = departements_page_soup.select_one(
            "div#accordion-listerub3501"
        ).find_all("a", class_="lien-sous-rubrique fr-link")

        departement_links = []
        for el in departements_links_elements:
            url = urljoin(PROJECTS_ARCHIVE_URL, el.get("href"))
            departement_name = el.get_text(strip=True)
            departement_links.append({"departement_name": departement_name, "url": url})

        sem = Semaphore(6)
        cors = [
            get_avis_listing_pages_links_from_departement_years_page(
                client, e["url"], e["departement_name"], sem
            )
            for e in departement_links
        ]
        avis_pages_links = await execute_coroutines(
            cors, tqdm_desc="AURA Archive - Getting all departements years links"
        )

        cors = [
            get_avis_links_listing_page_links_from_avis_listing_first_page(
                client,
                e["url"],
                e["departement_name"],
                e["year"],
                sem,
            )
            for e in avis_pages_links
        ]
        avis_listing_pages_links = await execute_coroutines(
            cors, tqdm_desc="AURA Archive - Getting all avis listing page links"
        )

        cors = [
            get_avis_pages_links_from_listing_page(
                client, e["url"], e["departement_name"], e["year"], sem
            )
            for e in avis_listing_pages_links
            if not (
                (e["departement_name"] in OLD_AVIS_DEPARTEMENTS) and (e["year"] == 2016)
            )
        ]
        all_avis_pages_links = await execute_coroutines(
            cors, tqdm_desc="AURA Archive - Getting all avis page links"
        )

        cors = [
            get_avis_from_avis_page_link(
                client,
                e["url"],
                e["departement_name"],
                e["year"],
                e["communes_names"],
                sem,
            )
            for e in all_avis_pages_links
        ]
        all_avis = await execute_coroutines(
            cors, tqdm_desc="AURA Archive - Getting all avis", list_result=False
        )
        avis.extend(all_avis)

        cors = [
            get_avis_from_old_avis_page(client, e["url"], e["departement_name"], sem)
            for e in avis_listing_pages_links
            if (
                (e["departement_name"] in OLD_AVIS_DEPARTEMENTS) and (e["year"] == 2016)
            )
        ]
        all_old_avis = await execute_coroutines(
            cors, tqdm_desc="AURA Archive - Getting all old avis", list_result=True
        )
        avis.extend(all_old_avis)

    return (
        pd.DataFrame([e for e in avis if e is not None])
        .drop_duplicates(subset=["pdf_url"])
        .reset_index(drop=True)
    )


async def execute_coroutines(
    coroutines: list, tqdm_desc: str | None, list_result: bool = True
) -> list[dict]:
    """
    Execute a list of coroutines concurrently with progress tracking.

    Parameters
    ----------
    coroutines : list
        List of coroutine objects to execute.
    tqdm_desc : str | None
        Description for the progress bar.
    list_result : bool, optional
        If True, flattens the results into a single list.
        If False, returns the raw gathered results. Default is True.

    Returns
    -------
    list[dict]
        List of results from the executed coroutines.
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


async def get_avis_listing_pages_links_from_departement_years_page(
    client: AsyncClient, url: str, departement_name: str, semaphore: asyncio.Semaphore
) -> list[dict]:
    """
    Extract links to avis listing pages from a departement's years page.

    Parses the HTML of a departement archive page to find links to
    yearly avis listings. Handles specific cases like 'Avis ex-Auvergne'.

    Parameters
    ----------
    client : AsyncClient
        The async HTTP client.
    url : str
        The URL of the departement years page.
    departement_name : str
        The name of the departement.
    semaphore : asyncio.Semaphore
        Semaphore to limit concurrent requests.

    Returns
    -------
    list[dict]
        List of dictionaries containing 'departement_name', 'year', and 'url'.
    """
    links_to_skip = ["Par ordre alphabétique des communes", "Nouvelle rubrique"]

    departements_years_links = []

    async with semaphore:
        departement_years_soup = await get_soup_from_url(client, url)

    if departement_name == "Avis ex-Auvergne (en cours de classement)":
        links_elements = departement_years_soup.select_one(
            "div.liste-rubriques.fr-mt-6w"
        ).select("a.fr-tile__link")
        for el in links_elements:
            if "Énergie" in el.get_text(strip=True):
                return [
                    {
                        "departement_name": departement_name,
                        "year": None,
                        "url": urljoin(PROJECTS_ARCHIVE_URL, el.get("href")),
                    }
                ]

    else:
        rubriques_with_subitems_elements = departement_years_soup.select_one(
            "div.liste-rubriques.fr-mt-6w"
        ).select("div.rubrique_avec_sous-rubriques")

        rubriques_elements = departement_years_soup.select_one(
            "div.liste-rubriques.fr-mt-6w"
        ).select("div.item-liste-rubriques-seule.fr-enlarge-link.fr-mb-4w")

        for el in rubriques_with_subitems_elements:
            year = el.select_one("p.fr-tile__title.fr-h3").get_text(strip=True)
            if any(e in year for e in links_to_skip):
                continue  # Not relevant

            links_elements = el.select("a.lien-sous-rubrique.fr-link")
            for el_subitem in links_elements:
                departements_years_links.append(
                    {
                        "departement_name": departement_name,
                        "year": extract_year_from_rubrique_text(year),
                        "url": urljoin(PROJECTS_ARCHIVE_URL, el_subitem.get("href")),
                    }
                )

        for el in rubriques_elements:
            link_el = el.select_one("a.fr-tile__link")
            year = link_el.get_text(strip=True)

            if any(e in year for e in links_to_skip):
                continue  # Not relevant
            departements_years_links.append(
                {
                    "departement_name": departement_name,
                    "year": extract_year_from_rubrique_text(year),
                    "url": urljoin(PROJECTS_ARCHIVE_URL, link_el.get("href")),
                }
            )

    await asyncio.sleep(random.uniform(0.3, 1.5))
    return departements_years_links


def extract_year_from_rubrique_text(rubrique_text: str) -> int | None:
    """
    Extract the year from a rubrique text string.

    Parameters
    ----------
    rubrique_text : str
        The text of the rubrique containing a year.

    Returns
    -------
    int | None
        The extracted year as an integer, or None if not found.
    """
    year = None
    match_o = re.search(r"([0-9]{4})", rubrique_text, flags=re.I)
    if match_o is not None:
        year = int(match_o.group(1))
    return year


async def get_avis_links_listing_page_links_from_avis_listing_first_page(
    client: AsyncClient,
    url: str,
    departement_name: str | None,
    year: int | None,
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    """
    Extract links to all avis listing pages from the first listing page.

    Parameters
    ----------
    client : AsyncClient
        The async HTTP client.
    url : str
        The URL of the first listing page.
    departement_name : str | None
        The name of the departement.
    year : int | None
        The year associated with the listing.
    semaphore : asyncio.Semaphore
        Semaphore to limit concurrent requests.

    Returns
    -------
    list[dict]
        List of dictionaries containing 'departement_name', 'year', and 'url'
        for each listing page.
    """
    avis_listings_links = []

    async with semaphore:
        soup = await get_soup_from_url(client, url)

    urls = build_listing_pages_urls(soup, url)

    for url_tmp in urls:
        avis_listings_links.append(
            {"departement_name": departement_name, "year": year, "url": url_tmp}
        )
    await asyncio.sleep(random.uniform(0.3, 1.5))
    return avis_listings_links


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
    urls = [urljoin(PROJECTS_ARCHIVE_URL, first_page_url)]

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
                PROJECTS_ARCHIVE_URL,
                re.sub(
                    r"debut_listearticles=[0-9]+",
                    f"debut_listearticles={offset}",
                    last_page_url,
                ),
            )
        )

    return urls


async def get_avis_pages_links_from_listing_page(
    client: AsyncClient,
    url: str,
    departement_name: str,
    year: int | None,
    semaphore: asyncio.Semaphore,
) -> list[dict]:
    """
    Extract links to avis pages from a listing page.

    Filters avis based on a project filter and extracts commune names.

    Parameters
    ----------
    client : AsyncClient
        The async HTTP client.
    url : str
        The URL of the listing page.
    departement_name : str
        The name of the departement.
    year : int | None
        The year associated with the listing.
    semaphore : asyncio.Semaphore
        Semaphore to limit concurrent requests.

    Returns
    -------
    list[dict]
        List of dictionaries containing 'departement_name', 'year',
        'communes_names', and 'url' for each avis page.
    """
    avis_pages_links = []
    async with semaphore:
        soup = await get_soup_from_url(client, url)

    cards_elements = soup.select("div.fr-card__content")

    for card_el in cards_elements:
        card_desc = card_el.select_one("p.fr-card__desc.fr-mt-1w")
        a_el = card_el.select_one("a.fr-card__link.article-card-lien")

        card_desc_text = ""
        if (card_desc) is not None:
            card_desc_text = card_desc.get_text(strip=True)
        a_text = ""
        if a_el is not None:
            a_text = a_el.get_text(strip=True)

        if not (project_filter(card_desc_text) or project_filter(a_text)):
            continue

        communes_names = extract_individual_communes(a_text)

        avis_page_url = a_el.get("href")
        avis_pages_links.append(
            {
                "departement_name": departement_name,
                "year": year,
                "communes_names": communes_names,
                "url": urljoin(PROJECTS_ARCHIVE_URL, avis_page_url),
            }
        )

    await asyncio.sleep(random.uniform(0.1, 1.2))

    return avis_pages_links


def extract_individual_communes(communes_names_raw: str) -> list[str]:
    """
    Extract individual commune names from a raw string.

    Splits the raw string by commas and ' et ' to isolate each commune.

    Parameters
    ----------
    communes_names_raw : str
        The raw string containing commune names.

    Returns
    -------
    list[str]
        List of individual commune names.
    """
    return re.split(r", | et ", communes_names_raw.replace("\xa0", " ").split(" : ")[0])


async def get_avis_from_avis_page_link(
    client: AsyncClient,
    url: str,
    departement_name: str,
    year: int | None,
    communes_names: list[str] | None,
    semaphore: asyncio.Semaphore,
) -> dict:
    """
    Extract avis details from an avis page link.

    Parses the avis page to extract title, date, PDF link, and metadata.

    Parameters
    ----------
    client : AsyncClient
        The async HTTP client.
    url : str
        The URL of the avis page.
    departement_name : str
        The name of the departement.
    year : int | None
        The year associated with the avis.
    communes_names : list[str] | None
        List of commune names associated with the avis.
    semaphore : asyncio.Semaphore
        Semaphore to limit concurrent requests.

    Returns
    -------
    dict
        Dictionary containing avis metadata, or None if PDF is missing.
    """
    async with semaphore:
        soup = await get_soup_from_url(client, url)

    article_el = soup.select_one("div.contenu-article")

    title = article_el.select_one(
        "div.texte-article.fr-text.fr-mt-8w.fr-mb-3w"
    ).get_text(strip=True)
    date_raw = re.search(r"[0-9]{1,2} [a-zéù]+ [0-9]{4}", title, flags=re.I)
    date = None
    try:
        date = datetime.strptime("%d %B %Y", date_raw.group(0))
    except Exception as exc:
        logger.debug(exc)
        if year is not None:
            date = datetime(year, 1, 1)

    a_el = article_el.select_one("a.fr-download__link")
    if a_el is None:
        return None

    pdf_url = a_el.get("href")
    pdf_filename = Path(pdf_url).name

    return get_scraped_avis_dict(
        project_name=title,
        communes_names=(
            [sanitize_geo_name(e) for e in communes_names]
            if communes_names is not None
            else None
        ),
        departement_name=sanitize_geo_name(departement_name),
        project_date=date,
        pdf_filename=pdf_filename,
        pdf_url=urljoin(PROJECTS_ARCHIVE_URL, pdf_url),
    )


def sanitize_geo_name(geo_name: str | None) -> str | None:
    """
    Sanitize a geographical name by removing the departement code in parentheses.

    Parameters
    ----------
    geo_name : str | None
        The raw geographical name.

    Returns
    -------
    str | None
        The sanitized name without the parenthetical code, or None.
    """
    if geo_name is None:
        return
    if "(" in geo_name:
        return geo_name[: geo_name.index("(")].strip()
    return geo_name


async def get_avis_from_old_avis_page(
    client: AsyncClient, url: str, departement_name: str, semaphore: asyncio.Semaphore
) -> list[dict]:
    """
    Extract avis details from an old avis page structure.

    Iterates through years and extracts avis metadata from legacy page layouts.

    Parameters
    ----------
    client : AsyncClient
        The async HTTP client.
    url : str
        The URL of the old avis page.
    departement_name : str
        The name of the departement.
    semaphore : asyncio.Semaphore
        Semaphore to limit concurrent requests.

    Returns
    -------
    list[dict]
        List of dictionaries containing avis metadata.
    """
    all_avis = []

    async with semaphore:
        soup = await get_soup_from_url(client, url)

    years_links_elements = soup.select("a.fr-card__link.article-card-lien")

    years_links = []
    for el in years_links_elements:
        url = el.get("href")

        year = None
        year_match = re.search(r"[0-4]{4}", el.get_text(strip=True))
        if year_match is not None:
            year = int(year_match.group(0))

        years_links.append({"year": year, "url": urljoin(PROJECTS_ARCHIVE_URL, url)})

    for year_link in years_links:
        async with semaphore:
            year_soup = await get_soup_from_url(client, year_link["url"])

        avis = extract_relevant_avis_from_old_avis_page(
            year_soup, departement_name, year_link["year"]
        )
        if len(avis) > 0:
            all_avis.extend(avis)

    return all_avis


def extract_relevant_avis_from_old_avis_page(
    soup: BeautifulSoup, departement_name: str, year: int
) -> list[dict]:
    """
    Extract relevant avis details from an old avis page soup.

    Filters and parses items to extract project names, communes, dates, and PDF links.

    Parameters
    ----------
    soup : BeautifulSoup
        The parsed HTML content of the old avis page.
    departement_name : str
        The name of the departement.
    year : int
        The year associated with the avis.

    Returns
    -------
    list[dict]
        List of dictionaries containing avis metadata.
    """
    avis = []
    article_el = soup.select_one("div.texte-article")

    for item in article_el.contents:
        if (item == "\n") or (item == ""):
            continue

        if (item.name == "div") and ("fr-downloads-group" in item.get("class")):
            continue

        item_text = item.get_text(strip=True)
        if not project_filter(item_text):
            continue

        next_sibling_el = item.next_sibling
        while (next_sibling_el == "\n") or (next_sibling_el == ""):
            next_sibling_el = next_sibling_el.next_sibling
            if next_sibling_el is None:
                continue

        if next_sibling_el.name != "div":
            continue

        communes_names = extract_communes_names_from_project_name(item_text)

        a_el = next_sibling_el.select_one("a.fr-download__link")
        a_text = a_el.contents[0].strip()
        avis_date = extract_avis_date_from_avis_link_text(a_text) or datetime(
            year, 1, 1
        )

        pdf_url = a_el.get("href")
        pdf_filename = Path(pdf_url).name

        avis.append(
            get_scraped_avis_dict(
                project_name=item_text,
                communes_names=communes_names,
                departement_name=sanitize_geo_name(departement_name),
                project_date=avis_date,
                pdf_filename=pdf_filename,
                pdf_url=urljoin(PROJECTS_ARCHIVE_URL, pdf_url),
            )
        )

    return avis


def extract_communes_names_from_project_name(project_name: str) -> list[str] | None:
    """
    Extract commune names from a project name string.

    Splits the project name by ':' and extracts the commune names
    from the first part, further splitting by '/' or ', '.

    Parameters
    ----------
    project_name : str
        The raw project name string, potentially containing commune
        names followed by a colon and the project description.

    Returns
    -------
    list[str] | None
        List of individual commune names if the project name contains
        a colon-separated structure, otherwise None.
    """
    splitted = project_name.split(":")
    if len(splitted) == 1:
        return None

    communes_names_raw = splitted[0].lstrip("-").strip()

    return re.split(r"(\/)|(, )", communes_names_raw)


def extract_avis_date_from_avis_link_text(link_text: str) -> datetime | None:
    """
    Extract the avis date from a link text string.

    Searches for a date pattern in the format DD/MM/YYYY within
    the provided link text and parses it into a datetime object.

    Parameters
    ----------
    link_text : str
        The text content of a link, potentially containing a date
        in DD/MM/YYYY format.

    Returns
    -------
    datetime | None
        The parsed datetime object if a valid date is found,
        otherwise None.
    """
    avis_date = None
    match_o = re.search(r"[0-9]{1,2}\/[0-9]{1,2}\/[0-9]{4}", link_text)
    try:
        avis_date = datetime.strptime(match_o.group(), r"%d/%m/%Y")
    except Exception as exc:
        logger.debug(exc)

    return avis_date


async def get_all_cas_par_cas_avis(client: AsyncClient) -> list[dict]:
    """
    Retrieve all 'cas par cas' avis from the dedicated archive page.

    Scrapes the cas par cas archive listing pages to extract avis
    page links, then fetches and parses each avis page to extract
    metadata and PDF URLs.

    Parameters
    ----------
    client : AsyncClient
        The async HTTP client for making requests.

    Returns
    -------
    list[dict]
        List of dictionaries containing avis metadata for all
        'cas par cas' projects found in the archive.
    """
    all_cas_par_cas_listing_pages_links = (
        await get_avis_links_listing_page_links_from_avis_listing_first_page(
            client,
            CAS_PAR_CAS_ARCHIVE_URL,
            None,
            None,
            Semaphore(1),
        )
    )

    sem = Semaphore(6)
    cors = [
        get_avis_pages_links_from_listing_page(
            client, e["url"], e["departement_name"], e["year"], sem
        )
        for e in all_cas_par_cas_listing_pages_links
    ]
    all_avis_pages_links = await execute_coroutines(
        cors, tqdm_desc="AURA Cas par Cas Archive - Getting all avis page links"
    )

    cors = [
        get_cas_par_cas_avis_from_avis_page_link(
            client,
            e["url"],
            e["communes_names"],
            sem,
        )
        for e in all_avis_pages_links
    ]
    all_avis = await execute_coroutines(
        cors, tqdm_desc="AURA Cas par Cas Archive - Getting all avis", list_result=False
    )

    return all_avis


async def get_cas_par_cas_avis_from_avis_page_link(
    client: AsyncClient,
    url: str,
    communes_names: list[str] | None,
    semaphore: asyncio.Semaphore,
) -> dict | None:
    """
    Extract avis details from a 'cas par cas' avis page.

    Parses the avis page to extract the project title, decision date,
    PDF link, and metadata. Specifically looks for links containing
    'décision' in the text.

    Parameters
    ----------
    client : AsyncClient
        The async HTTP client for making requests.
    url : str
        The URL of the avis page.
    communes_names : list[str] | None
        List of commune names associated with the avis.
    semaphore : asyncio.Semaphore
        Semaphore to limit concurrent requests.

    Returns
    -------
    dict | None
        Dictionary containing avis metadata, or None if no decision
        link is found on the page.
    """
    async with semaphore:
        soup = await get_soup_from_url(client, url)

    title = soup.select_one("h1.titre-article").get_text(strip=True)
    article_el = soup.select_one("div.contenu-article")

    a_elements = article_el.select("a.fr-download__link")

    relevant_a = None
    for a_el in a_elements:
        a_text = a_el.contents[0]
        if "décision" in a_text.lower():
            relevant_a = a_el
            break

    if relevant_a is None:
        return None

    date_raw = relevant_a.contents[0].strip()
    date = extract_date_from_cas_par_cas_link_text(date_raw)

    pdf_url = relevant_a.get("href")
    pdf_filename = Path(pdf_url).name
    departement_name = extract_departement_name_from_communes_names(communes_names)

    return get_scraped_avis_dict(
        project_name=title,
        communes_names=[sanitize_geo_name(e) for e in communes_names],
        departement_name=departement_name,
        project_date=date,
        pdf_filename=pdf_filename,
        pdf_url=urljoin(CAS_PAR_CAS_ARCHIVE_URL, pdf_url),
    )


DEPARTEMENTS_MAP = {
    "01": "Ain",
    "03": "Allier",
    "07": "Ardèche",
    "15": "Cantal",
    "26": "Drôme",
    "38": "Isère",
    "42": "Loire",
    "43": "Haute-Loire",
    "63": "Puy-de-Dôme",
    "69": "Rhône",
    "73": "Savoie",
    "74": "Haute-Savoie ",
}


def extract_departement_name_from_communes_names(
    communes_names: list[str],
) -> str | None:
    """
    Extract the departement name from a list of commune names.

    Searches through the commune names for a two-digit departement
    code in parentheses and maps it to the corresponding departement
    name using the DEPARTEMENTS_MAP.

    Parameters
    ----------
    communes_names : list[str]
        List of commune names, potentially containing departement
        codes in parentheses (e.g., 'Lyon (69)').

    Returns
    -------
    str | None
        The departement name if a valid departement code is found,
        otherwise None.
    """
    departement_name = None
    for commune_name in communes_names:
        if commune_name is None:
            continue
        match_o = re.search(r"\(([0-9]{2})\)", commune_name)
        if match_o is not None:
            departement_name = DEPARTEMENTS_MAP.get(match_o.group(1))

    return departement_name


def extract_date_from_cas_par_cas_link_text(link_text: str) -> datetime | None:
    """
    Extract the date from a 'cas par cas' link text string.

    Searches for a date pattern in the format 'DD month YYYY'
    (with French month names) within the provided link text and
    parses it into a datetime object.

    Parameters
    ----------
    link_text : str
        The text content of a link, potentially containing a date
        with a French month name (e.g., '15 janvier 2023').

    Returns
    -------
    datetime | None
        The parsed datetime object if a valid date is found,
        otherwise None.
    """
    date = None
    match_o = re.search(r"[0-9]{1,2} [a-zùà]+ [0-9]{4}", link_text, flags=re.I)
    if match_o is not None:
        try:
            date = datetime.strptime(match_o.group(), "%d %B %Y")
        except Exception as exc:
            logger.debug(exc)

    return date


if __name__ == "__main__":
    asyncio.run(get_aura_archive_pdf_urls_and_metadata())
