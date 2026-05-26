import pandas as pd

from .extract_relevant_pdf_links import get_all_pdfs_metadata_df
from .extract_year_links import get_mrae_links
from .urls import MRAE_URLS


async def get_mrae_pdf_urls_and_metadata() -> pd.DataFrame:
    """Extract AE PDF links and metadata from MRAE websites.

    Scrapes all regional MRAE websites to find relevant AEs,
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
    >>> df = asyncio.run(get_mrae_pdf_urls_and_metadata())
    """
    results = []
    for region_name, region_url in MRAE_URLS.items():
        data = get_mrae_links(region_url, region_name)
        results.extend(data)

    year_links_df = pd.DataFrame(results)
    pdfs_metadata_df = await get_all_pdfs_metadata_df(year_links_df)

    return pdfs_metadata_df
