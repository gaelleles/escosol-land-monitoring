import logging
import os
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl
import pymupdf4llm
from tqdm import tqdm

from extraction import (
    extract_presentation,
    extract_max_land_surface,
    extract_max_power,
    extract_commune_and_departement,
)

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def extract_data_from_text(text: str) -> dict[str, Any]:
    ha = None
    mwc = None
    location_dict = {"departement_code": None, "communes": []}

    if (text is None) or (pd.isna(text)):
        return {"land_surface_ha": ha, "power_mwc": mwc, **location_dict}

    context = extract_presentation(text)
    if context is not None:
        ha = extract_max_land_surface(context)
        mwc = extract_max_power(context)
        location_dict = extract_commune_and_departement(context)

    if ha is None:
        ha = extract_max_land_surface(text)
    if mwc is None:
        mwc = extract_max_power(text)
    if any(v is None for v in location_dict.values()):
        location_dict_text = extract_commune_and_departement(text)
        location_dict = {
            "departement_code": location_dict["departement_code"]
            if location_dict["departement_code"] is not None
            else location_dict_text["departement_code"],
            "communes": location_dict["communes"] + location_dict_text["communes"],
        }
    data = {"land_surface_ha": ha, "power_mwc": mwc, **location_dict}

    return data


def process_all_pdfs_texts(pdf_df: pd.DataFrame):
    results = []
    pdfs_with_errors = []
    for _, row in tqdm(pdf_df.iterrows()):
        metadata = row
        raw_text = row["text"]
        filename = row["pdf_name"]
        try:
            data = extract_data_from_text(raw_text)
            data_project_name = extract_data_from_text(metadata["project_name"])

            result = {
                **metadata,
                "pdf_name": filename,
                "text": raw_text,
                "land_surface_ha_from_text": data["land_surface_ha"],
                "power_mwc_from_text": data["power_mwc"],
                "departement_code_from_text": data["departement_code"],
                "communes_from_text": data["communes"],
                "land_surface_ha_from_title": data_project_name["land_surface_ha"],
                "power_mwc_from_title": data_project_name["power_mwc"],
                "departement_code_from_title": data_project_name["departement_code"],
                "communes_from_title": data_project_name["communes"],
            }
            results.append(result)

        except Exception as e:
            print(f"Erreur sur {filename}: {e}")
            pdfs_with_errors.append(filename)

    print("PDFs with errors :")
    print(pdfs_with_errors)

    pd.DataFrame(results).to_parquet(
        output_path / f"_pdf_extraction_results_{datetime.now():%Y_%m_%d}.parquet",
        index=False,
    )


def process_all_pdfs_files(
    folder_path: Path, output_path: Path, pdf_metadata_df: pd.DataFrame
):
    """
    Process all PDF files in the specified folder
    and extract land surface and power data then save it as a CSV file in output_path folder.
    """

    pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith(".pdf")]

    results = []
    pdfs_with_errors = []
    for filename in tqdm(pdf_files):
        filename_search_df = pdf_metadata_df.loc[
            pdf_metadata_df["pdf_filename"] == filename
        ]
        if len(filename_search_df) == 0:
            logger.debug("Metadata not found for file %s", filename)
            pdfs_with_errors.append(filename)
            continue
        metadata = filename_search_df.iloc[0].to_dict()
        try:
            # 1. Extraction texte brut
            raw_text: str = pymupdf4llm.to_markdown(
                folder_path / filename,
                header=False,
                footer=False,
                ignore_code=True,
                ignore_graphics=True,
                ignore_images=True,
                ocr_language="fra",
            )  # type: ignore

            data = extract_data_from_text(raw_text)
            data_project_name = extract_data_from_text(metadata["project_name"])

            result = {
                "pdf_name": filename,
                "text": raw_text,
                "land_surface_ha_from_text": data["land_surface_ha"],
                "power_mwc_from_text": data["power_mwc"],
                "departement_code_from_text": data["departement_code"],
                "communes_from_text": data["communes"],
                "land_surface_ha_from_title": data_project_name["land_surface_ha"],
                "power_mwc_from_title": data_project_name["power_mwc"],
                "departement_code_from_title": data_project_name["departement_code"],
                "communes_from_title": data_project_name["communes"],
                **metadata,
            }
            results.append(result)

        except Exception as e:
            print(f"Erreur sur {filename}: {e}")
            pdfs_with_errors.append(filename)

    print("PDFs with errors :")
    print(pdfs_with_errors)

    pd.DataFrame(results).to_parquet(
        output_path / f"_pdf_extraction_results_{datetime.now():%Y_%m_%d}.parquet",
    )


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        "pdf_to_data",
        description="Extract data from AE PDFs. Result is saved in a file pdf_extraction_result.csv.",
    )
    arg_parser.add_argument(
        "pdf_path",
        help="Path of the folder where are PDFs are located or path to a parquet dataset containing pdf_name and pdf_text columns.",
        type=Path,
    )
    arg_parser.add_argument(
        "pdf_metadata_csv_filepath",
        help="Path of the CSV file containing pdf metadata.",
        type=Path,
    )

    arg_parser.add_argument(
        "-o",
        "--output_path",
        help="Path of the folder where the CSV containing extracted data will be saved. Default to pdf_path.",
        dest="output_path",
        type=Path,
    )

    args = arg_parser.parse_args()
    pdf_path = Path(args.pdf_path)

    if pdf_path.is_dir():
        output_path = pdf_path
        if args.output_path is not None:
            output_path = Path(args.output_path)

        metadata_df = pd.read_csv(args.pdf_metadata_csv_filepath)
        process_all_pdfs_files(pdf_path, output_path, metadata_df)

    elif pdf_path.is_file():
        output_path = pdf_path.parent
        if args.output_path is not None:
            output_path = Path(args.output_path)
        df = pd.read_parquet(pdf_path)

        process_all_pdfs_texts(df)
