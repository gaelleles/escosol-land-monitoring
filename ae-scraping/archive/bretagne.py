"""
Module containing utilities to scrape Bretagne AE archive website
(https://www.bretagne.developpement-durable.gouv.fr/avis-de-l-ae-sur-projets-jusqu-en-2017-r743.html)
and extract relevant AE metadata and PDFs.
"""

from datetime import datetime
import logging
import re
from pathlib import Path
from urllib.parse import urljoin

import pandas as pd
from tqdm import tqdm


from ..config import get_http_client
from ..utils.scraping import get_soup_from_url
from ..utils.data import get_scraped_avis_dict

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

ARCHIVE_URL = "https://www.bretagne.developpement-durable.gouv.fr/avis-de-l-ae-sur-projets-jusqu-en-2017-r743.html"


async def get_bretagne_archive_pdf_urls_and_metadata() -> pd.DataFrame:
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
        - year : str
            Year when the avis was published (if available)
        - pdf_filename : str or None
            Filename of the PDF document
        - pdf_url : str
            Full URL to the PDF document

    Examples
    --------
    >>> import asyncio
    >>> df = asyncio.run(get_bretagne_archive_pdf_urls_and_metadata())
    """

    avis = []

    bretagne_archive_url = ARCHIVE_URL
    async with get_http_client() as client:
        years_links: list[dict] = []
        soup = await get_soup_from_url(client, bretagne_archive_url)

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
            year_soup = await get_soup_from_url(
                client, urljoin(bretagne_archive_url, link)
            )

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

        for e in tqdm(departements_links, desc="Extracting Bretagne AE PDFs link"):
            departement_name = e["name"]
            year = int(e["year"])
            departement_link = e["url"]

            departement_soup = await get_soup_from_url(
                client, urljoin(bretagne_archive_url, departement_link)
            )

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
                            for e in ["solaire", "voltaïque", "voltaique"]
                        ):
                            pdf_div = sibling.next_sibling
                            if pdf_div == "\n":
                                pdf_div = (
                                    pdf_div.next_sibling
                                )  # To avoid hitting newlines between page elements
                            if (pdf_div.name == "h2") or (pdf_div.name == "p"):
                                continue  # Sometimes there is no PDF link so we continue to next item

                            document_url: str = pdf_div.find("a").get("href")
                            document_name = Path(document_url).name
                            avis.append(
                                get_scraped_avis_dict(
                                    project_name=project_name,
                                    communes_names=[commune_name],
                                    departement_name=departement_name,
                                    project_date=datetime(year, 1, 1),
                                    pdf_filename=document_name,
                                    pdf_url=urljoin(bretagne_archive_url, document_url),
                                )
                            )

    return pd.DataFrame(avis)
