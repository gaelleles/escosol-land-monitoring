# Access pages and extract links to avis projet x année
import logging
import re
from argparse import ArgumentParser
from pathlib import Path
from urllib.parse import urljoin

import httpx
import pandas as pd
from bs4 import BeautifulSoup
from tqdm import tqdm

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def get_mrae_links(base_url=None, region=None):
    """
    Récupère les liens vers les pages annuelles des avis de projets MRAE
    pour une région donnée.

    :param base_url: url de la page régionale MRAE
    :param region: région
    """
    timeout_config = httpx.Timeout(60.0, connect=10.0)

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }
    all_links = []
    current_url = base_url

    with httpx.Client(
        headers=headers, timeout=timeout_config, follow_redirects=True
    ) as client:
        while current_url:
            response = client.get(current_url)
            response.raise_for_status()
            soup = BeautifulSoup(response.text, "html.parser")

            links = soup.select("h2.fr-card__title a")
            for a in links:
                full_url = urljoin(base_url, a["href"])
                year = re.search(r"(\d{4})", a["title"]).group(1)
                all_links.append([base_url, region, year, full_url])

            next_page = soup.select_one("a.fr-pagination__link--next")
            if next_page and next_page.get("href"):
                current_url = urljoin(base_url, next_page["href"])
            else:
                current_url = None

    return all_links


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        "extract_year_links",
        description="Program that scrapes the links of MRAe website pages that list PDFs for each year and region. "
        "Needs the CSV file region_links_ae.csv as input. "
        "Output a new CSV file ae_year_links.csv.",
    )
    arg_parser.add_argument(
        "region_links_ae_csv_filepath", help="Path to the csv file region_links_ae.csv."
    )
    arg_parser.add_argument(
        "-o",
        "--output_path",
        help="Path where to output the resulting metadata_pdfs.csv file."
        "Default to same folder as region_links_ae.csv.",
        dest="output_path",
    )

    args = arg_parser.parse_args()
    region_links_ae_csv_filepath = Path(args.region_links_ae_csv_filepath)
    output_path = region_links_ae_csv_filepath.parent
    if args.output_path is not None:
        output_path = Path(args.output_path)

    results = []
    region_links = pd.read_csv(region_links_ae_csv_filepath)
    for _, row in tqdm(region_links.iterrows(), total=region_links.shape[0]):
        data = get_mrae_links(row["site"], row["region"])
        results.extend(data)

    df_results = pd.DataFrame(results)
    df_results.columns = ["base_url", "region", "year", "year_url"]
    df_results.to_csv(output_path / "ae_year_links.csv", index=False)
