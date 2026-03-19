import asyncio
import logging
from argparse import ArgumentParser
import os
from pathlib import Path

import pandas as pd
from archive.side import get_side_archive_pdf_urls_and_metadata
from archive.bretagne import get_bretagne_archive_pdf_and_metadata
from archive.utils import download_pdfs

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        description="Program that scrapes the URLs of MRAe archive website pages that list PDFs of AE."
        "Output a new CSV file archive_pdf_links.csv and downloads the PDF files."
        "use --metadata-only or --metadata-filepath options to skip parts of the process.",
    )
    arg_parser.add_argument(
        "--metadata-only",
        help="Use this option to only create the CSV files containing the PDF URLs and metadata and avoid downloading all PDFs.",
        action="store_true",
        dest="metadata_only",
    )
    arg_parser.add_argument(
        "--metadata-filepath",
        help="Filepath to metadata file archive_pdf_links.csv."
        "Use this option to download PDFs from already created archive_pdf_links.csv file and skip scraping part.",
        type=Path,
        dest="metadata_filepath",
    )
    arg_parser.add_argument(
        "-o",
        "--output_path",
        help="Path where to output the resulting archive_pdf_links.csv file and downloaded PDFs files."
        "Default to current working directory.",
        type=Path,
        dest="output_path",
    )
    arg_parser.add_argument(
        "--verbose", help="Set logging to debug level.", action="store_true"
    )

    args = arg_parser.parse_args()

    if args.verbose:
        logger.setLevel(logging.DEBUG)

    output_path = Path(os.getcwd())
    if args.output_path is not None:
        output_path = args.output_path

    df = None
    if args.metadata_filepath is not None:
        logger.info("Reading archive metadata CSV files...")
        df = pd.read_csv(args.metadata_filepath)
    else:
        df_side = asyncio.run(get_side_archive_pdf_urls_and_metadata())
        df_bretagne = asyncio.run(get_bretagne_archive_pdf_and_metadata())

        df = pd.concat([df_side, df_bretagne])
        df.to_csv(output_path / "archive_pdf_links.csv", index=False)

    if (args.metadata_only is not None) and not args.metadata_only:
        logger.info("Starting PDFs downloading...")
        asyncio.run(download_pdfs(df, output_path))
