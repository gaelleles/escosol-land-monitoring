"""
Module containing utilities to scrape SIDE
(https://side.developpement-durable.gouv.fr/accueil-side.aspx) website
and extract relevant AE metadata and PDFs.
"""

import asyncio
import logging
import re
import time
from datetime import datetime

import pandas as pd
from selenium import webdriver
from selenium.webdriver import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from tqdm import tqdm

from ..config import get_http_client
from ..utils.data import get_scraped_avis_dict
from ..utils.scraping import get_soup_from_url

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

SIDE_ARCHIVE_URL = "https://side.developpement-durable.gouv.fr/search.aspx?SC=DEFAULT&QUERY=avis+projet&QUERY_LABEL=#/Search/(query:(FacetFilter:'%7B%22_95%22:%22CENTRALE%20PHOTOVOLTAIQUE%7C%7CENERGIE%20PHOTOVOLTAIQUE%22%7D',ForceSearch:!t,InitialSearch:!f,Page:0,PageRange:3,QueryGuid:'31d6a7c8-cf7d-43f3-89b0-cf2c8873dc4d',QueryString:'avis%20projet',ResultSize:50,ScenarioCode:DEFAULT,ScenarioDisplayMode:display-standard,SearchGridFieldsShownOnResultsDTO:!(),SearchLabel:'',SearchTerms:'avis%20projet',SortField:!n,SortOrder:0,TemplateParams:(Scenario:'',Scope:Default,Size:!n,Source:'',Support:'',UseCompact:!f),UseSpellChecking:!n),sst:4)"


def get_side_archive_items_links(driver: WebDriver) -> list[str]:
    """Extract AE item URLs from the current page of SIDE archive search results.

    Scrapes all notice elements from the current page and extracts their data-url
    attributes which link to individual document pages.

    Parameters
    ----------
    driver : WebDriver
        Selenium WebDriver instance with the SIDE archive search results page loaded.

    Returns
    -------
    list[str]
        List of URLs pointing to individual document detail pages.
    """

    items = driver.find_elements(
        By.XPATH,
        "//div[contains(@class,'notice notice_courte row')]",
    )

    urls = []
    for item in items:
        urls.append(item.get_attribute("data-url"))

    return urls


async def get_side_archive_pdf_url_and_name(
    parent_document_id: str,
) -> tuple[str, str] | None:
    """Retrieve AE PDF download URL and filename from SIDE document library.

    Queries the SIDE Digital Collection Service API to find downloadable AE documents
    associated with a given parent document ID, then constructs the direct download
    URL for the first available document.

    Parameters
    ----------
    parent_document_id : str
        The parent document identifier used to query the document library service.

    Returns
    -------
    tuple[str, str] | None
        A tuple containing (pdf_url, pdf_filename) if a document is found,
        otherwise None.
    """

    document_library_url = f"https://side.developpement-durable.gouv.fr/DigitalCollectionService.svc/ListDigitalDocuments?parentDocumentId={parent_document_id}&start=0&limit=10&includeMetaDatas=false"

    async with get_http_client() as client:
        res = await client.get(url=document_library_url)
        res.raise_for_status()
        json_res = res.json()

        documents = json_res.get("d", {}).get("documents", [])

        if len(documents) == 0:
            return None

        document_id = documents[0].get("documentId")
        document_filename = documents[0].get("fileName")

        if document_id is None:
            return None

    url = f"https://side.developpement-durable.gouv.fr/digitalCollection/DigitalCollectionAttachmentDownloadHandler.ashx?parentDocumentId={parent_document_id}&documentId={document_id}&skipWatermark=true&skipCopyright=true"

    return url, document_filename


async def get_side_archive_pdf_urls_and_metadata() -> pd.DataFrame:
    """Scrape SIDE archive to extract AE metadata and PDF download URLs.

    Performs a complete scrape of the SIDE archive website for relevant AE. Navigates through all pagination pages,
    extracts metadata from each document page, and retrieves associated PDF download links.

    Returns
    -------
    pd.DataFrame
        DataFrame containing columns: title, url, author, publisher, publish_date,
        pdf_filename, pdf_url for each scraped document.
    """

    options = webdriver.FirefoxOptions()
    options.add_argument("-headless")
    driver: WebDriver = webdriver.Firefox(options=options)
    wait = WebDriverWait(driver, timeout=30)

    logger.debug("Going to MRAE archive website.")
    driver.get(SIDE_ARCHIVE_URL)
    wait.until(EC.presence_of_element_located((By.CLASS_NAME, "notice")))

    cookies_button = driver.find_element(
        By.XPATH,
        "//button[contains(@class,'cookies-deny')]",
    )
    if cookies_button is not None:
        cookies_button.click()

    logger.debug("Getting documents links for page 1.")
    urls = get_side_archive_items_links(driver)

    next_page_li = driver.find_element(
        By.XPATH,
        "//ul[@class='pagination pagination-sm']/li[last()]",
    )

    page = 2

    while "disabled" not in next_page_li.get_attribute("class"):
        time.sleep(1)  # Needed as the actionchains does not fire
        logger.debug("Getting documents links for page %s.", page)

        ActionChains(driver).move_to_element(next_page_li).click().pause(2).perform()
        wait.until(
            EC.presence_of_element_located(
                (
                    By.XPATH,
                    f"//ul[@class='pagination pagination-sm']/li[@class='active'][span[text()='{page}']]",
                )
            )
        )

        urls.extend(get_side_archive_items_links(driver))

        next_page_li = driver.find_element(
            By.XPATH,
            "//ul[@class='pagination pagination-sm']/li[last()]",
        )
        page += 1

    results_list = []
    for url in tqdm(urls, desc="Extracting PDF links and metadata."):
        async with get_http_client() as client:
            soup = await get_soup_from_url(client, url)

            title = (
                soup.find("div", id="notice_longue_description")
                .find("h2")
                .text.replace("\\", "")
            )
            if "Avis" not in title:
                continue

            try:
                publish_date = datetime.strptime(
                    soup.find("p", class_="item-datepublication")
                    .text.split("Date de publication : ")[1]
                    .strip(),
                    "%d/%m/%Y",
                )
            except AttributeError:
                logger.debug("Publish date not found for url %s", url)
                publish_date = None

            parent_document_id = re.search(
                r"collectionId:'([0-9]+)'",
                soup.find("div", id="dr-viewer").find("script").text,
            ).group(1)

            pdf_url, pdf_filename = await get_side_archive_pdf_url_and_name(
                parent_document_id
            )

            result_object = get_scraped_avis_dict(
                project_name=title,
                communes_names=None,
                departement_name=None,
                project_date=publish_date,
                pdf_filename=pdf_filename,
                pdf_url=pdf_url,
            )
            results_list.append(result_object)
            await asyncio.sleep(0.5)

    return pd.DataFrame(results_list)
