"""
Module containing utilities to scrape Bretagne AE archive website
(https://www.bretagne.developpement-durable.gouv.fr/avis-de-l-ae-sur-projets-jusqu-en-2017-r743.html)
and extract relevant AE metadata and PDFs.
"""

import logging
import re
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import httpx
import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm
from tqdm.contrib.logging import logging_redirect_tqdm


from .config import HEADERS, RETRY_TRANSPORT, TIMEOUT_CONFIG, ARCHIVE_URLS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def get_bretagne_archive_pdf_and_metadata() -> pd.DataFrame:
    """Extract AE PDF links and metadata from Bretagne archive website.

    Scrapes the Bretagne AE archive to find relevant AEs,
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
        - document_name : str
            Filename of the PDF document
        - year : str or None
            Year when the avis was published (if available)
        - document_url : str
            Full URL to the PDF document

    Examples
    --------
    >>> import asyncio
    >>> df = asyncio.run(get_bretagne_archive_pdf_and_metadata())
    >>> print(df.columns.tolist())
    ['project_name', 'commune_name', 'departement_name', 'document_name', 'year', 'document_url']
    """

    avis = []

    bretagne_archive_url = ARCHIVE_URLS["Bretagne"]
    async with httpx.AsyncClient(
        headers=HEADERS,
        timeout=TIMEOUT_CONFIG,
        follow_redirects=True,
        transport=RETRY_TRANSPORT,
    ) as client:
        years_links: list[dict] = []
        res = await client.get(bretagne_archive_url)

        soup = BeautifulSoup(res.text, "html.parser")

        years_divs = soup.find_all(
            "div", class_="item-liste-rubriques-seule fr-enlarge-link fr-mb-4w"
        )
        for div in years_divs:
            url_element = div.find("a")
            url = url_element.get("href")

            year = None
            year_match = re.search(r"[0-9]{4}", url_element.text)
            if year_match is not None:
                year = year_match.group(0)

            years_links.append({"url": url, "year": year})

        departements_links = []
        for e in years_links:
            link = e["url"]
            year = e["year"]
            year_res = await client.get(urljoin(bretagne_archive_url, link))
            year_soup = BeautifulSoup(year_res.text, "html.parser")

            for departement_div in year_soup.find_all(
                "div", class_="item-liste-articles fr-card fr-enlarge-link"
            ):
                departement_link_element = departement_div.find("a")
                departement_name = departement_link_element.text
                departement_url = departement_link_element.get("href")
                departements_links.append(
                    {
                        "name": departement_name,
                        "year": year,
                        "url": departement_url,
                    }
                )

        with logging_redirect_tqdm():
            for e in tqdm(departements_links, desc="Extracting Bretagne AE PDFs link"):
                departement_name = e["name"]
                year = e["year"]
                departement_link = e["url"]

                departement_res = await client.get(
                    urljoin(bretagne_archive_url, departement_link)
                )
                departement_soup = BeautifulSoup(departement_res.text, "html.parser")

                communes_names_h2 = departement_soup.find(
                    "div", class_="texte-article fr-text fr-mt-8w fr-mb-3w"
                ).find_all("h2")
                for commune_name_h2 in communes_names_h2:
                    commune_name = commune_name_h2.text

                    for sibling in commune_name_h2.next_siblings:
                        if sibling == "\n":
                            continue

                        if sibling.name == "h2":
                            break

                        if sibling.name == "p":
                            project_name = sibling.text
                            if any(
                                e in project_name.lower().strip()
                                for e in ["solaire", "photovoltaïque", "photovoltaique"]
                            ):
                                pdf_div = sibling.next_sibling
                                if pdf_div == "\n":
                                    pdf_div = (
                                        pdf_div.next_sibling
                                    )  # To avoid hitting newlines between page elements
                                if (pdf_div.name == "h2") or (pdf_div.name == "p"):
                                    continue  # Sometimes there is no PDF link so we continue to next item

                                document_url: str = pdf_div.find("a").get("href")
                                document_name = Path(urlsplit(document_url).path).name
                                avis.append(
                                    {
                                        "project_name": project_name,
                                        "commune_name": commune_name,
                                        "departement_name": departement_name,
                                        "document_name": document_name,
                                        "year": year,
                                        "document_url": urljoin(
                                            bretagne_archive_url, document_url
                                        ),
                                    }
                                )

    return pd.DataFrame(avis)
