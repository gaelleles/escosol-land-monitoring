import logging
import os
import re
from argparse import ArgumentParser
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import polars as pl
import pymupdf.layout  # noqa: F401
import pymupdf4llm
from tqdm import tqdm

# Code adapted from the data4good sufficiency project
# https://github.com/dataforgoodfr/13_democratiser_sobriete
# Which covered similar issues of PDF text extraction

logging.basicConfig(level=logging.DEBUG)
logger = logging.getLogger(__name__)


def extract_context(input_text: str):
    """
    Extracts a section from markdown text without modifying the original input.
    """
    # 1. Regex to find headings, capturing the level (#) and the content
    # We use MULTILINE to find starts of lines
    heading_pattern = re.compile(r"^(#+)\s*(.*)$", re.MULTILINE)

    headings = []
    # We iterate over the input_text. This does not change input_text.
    for match in heading_pattern.finditer(input_text):
        level = len(match.group(1))
        # Clean the content from markdown bold/italic decorators for easier searching
        # We create a new string 'clean_content' here
        clean_content = match.group(2).strip("*_ ")

        # Try to find a section number (e.g., "1", "1.1", "2")
        root_match = re.search(r"^(\d+)", clean_content)
        root_number = root_match.group(1) if root_match else None

        headings.append(
            {
                "start": match.start(),
                "level": level,
                "root": root_number,
                "content": clean_content.lower(),
            }
        )

    # 2. Find the starting heading that matches our keywords
    start_heading = None
    for h in headings:
        if any(
            kw.lower() in h["content"]
            for kw in ["présentation", "contexte", "presentation"]
        ):
            start_heading = h
            break

    if not start_heading:
        return None

    # 3. Find the end index
    end_index = len(input_text)
    for h in headings:
        if h["start"] > start_heading["start"]:
            # Condition A: Higher level heading found (e.g., #)
            if h["level"] < start_heading["level"]:
                end_index = h["start"]
                break

            # Condition B: Same level but different section number (e.g., 2. vs 1.)
            if h["level"] == start_heading["level"]:
                if start_heading["root"] != h["root"]:
                    end_index = h["start"]
                    break

    # 4. Return a SLICE.
    # Slicing in Python creates a NEW string object.
    # The original input_text remains completely unchanged.
    return input_text[start_heading["start"] : end_index].strip()


def extract_commune_and_departement(
    text: str,
) -> dict[str, str | None | list[str]]:
    dept_match = re.search(r"\(([0-9][0-9ABO]|[0-9]{3})\)", text)
    if not dept_match:
        return {"departement_code": None, "communes": None}

    dept = dept_match.group(1).replace("O", "0")
    content_before = text[: dept_match.start()].strip()

    keywords = [
        r"sur les communes de",
        r"sur la commune d[’']",
        r"sur la commune de",
        r"commune de",
        r"commune d[’']",
        r" à ",
        r" d[’']",
        r" aux ",
        r" de ",
    ]

    last_pos = -1
    for kw in keywords:
        found = list(re.finditer(kw, content_before, re.IGNORECASE))
        if found:
            current_last_pos = found[-1].end()
            if current_last_pos > last_pos:
                last_pos = current_last_pos

    if last_pos == -1:
        return {"departement_code": dept, "communes": None}

    raw_names = content_before[last_pos:].strip()
    parts = re.split(r" et | & |,", raw_names)

    final_communes = []
    for p in parts:
        clean = re.sub(r'[«»"“”]', "", p).strip()
        clean = re.sub(r"^(de |d'|d’|le |la |les )", "", clean, flags=re.IGNORECASE)

        if any(char.isupper() for char in clean):
            final_communes.append(clean)

    return {"departement_code": dept, "communes": final_communes}


def extract_max_land_surface(text: str) -> float | None:
    ha = extract_max_ha(text)

    if ha:
        return ha

    m2 = extract_max_m2(text)
    if m2:
        return m2 / 10000

    return None


def extract_max_ha(text) -> float | None:
    pattern = r"(\d{1,3}(?:[\s]\d{3})*(?:[.,]\d+)?)\s*(?:ha\b|hectares?)"

    matches = re.findall(pattern, text, re.IGNORECASE)

    if not matches:
        return None

    return process_matches(matches, max_val=500)


def extract_max_m2(text) -> float | None:
    pattern = r"(\d{1,3}(?:[\s]\d{3})*(?:[.,]\d+)?)\s*(?:m2|m²)"

    matches = re.findall(pattern, text, re.IGNORECASE)

    if not matches:
        return None

    return process_matches(matches, max_val=1e6)


def extract_max_mwc(text: str) -> float | None:
    pattern = (
        r"(\d{1,3}(?:[\s]\d{3})*(?:[.,]\d+)?)\s*(?:MWc|megawatt-crête|Méga Watt crête)"
    )

    matches = re.findall(pattern, text, re.IGNORECASE)

    if not matches:
        return None

    return process_matches(matches, max_val=100)


def extract_max_kwc(text: str) -> float | None:
    pattern = r"(\d{1,3}(?:[\s]\d{3})*(?:[.,]\d+)?)\s*(?:kWc|kilowatt-crête)"

    matches = re.findall(pattern, text, re.IGNORECASE)

    if not matches:
        return None

    return process_matches(matches)


def extract_max_wc(text: str) -> float | None:
    pattern = r"(\d{1,3}(?:[\s]\d{3})*(?:[.,]\d+)?)\s*(?:Wc)"

    matches = re.findall(pattern, text, re.IGNORECASE)

    if not matches:
        return None

    return process_matches(matches)


def extract_max_power(text: str) -> float | None:
    mwc = extract_max_mwc(text)

    if mwc:
        return mwc

    kwc = extract_max_kwc(text)
    if kwc:
        return kwc / 1000

    wc = extract_max_wc(text)
    if wc:
        return wc / 1000000

    return None


def process_matches(matches: list[Any], max_val: float | None = None) -> float:
    valeurs = []
    for val in matches:
        val_propre = re.sub(r"\s+", "", val).replace(",", ".")
        valeurs.append(float(val_propre))

    if max_val:
        valeurs = [v for v in valeurs if v <= max_val]

    return max(valeurs, default=None)


def process_pdf_text(text: str) -> dict[str, Any]:
    ha = None
    mwc = None
    location_dict = {"departement_code": None, "communes": None}

    if (text is None) or (pd.isna(text)):
        return {"land_surface_ha": ha, "power_mwc": mwc, **location_dict}

    context = extract_context(text)
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
            "communes": location_dict["communes"]
            if location_dict["communes"] is not None
            else location_dict_text["communes"],
        }
    data = {"land_surface_ha": ha, "power_mwc": mwc, **location_dict}

    return data


def process_all_pdfs_texts(pdf_df: pl.DataFrame):
    results = []
    pdfs_with_errors = []
    for row in tqdm(pdf_df.iter_rows(named=True)):
        metadata = row
        raw_text = row["text"]
        filename = row["pdf_name"]
        try:
            data = process_pdf_text(raw_text)
            data_project_name = process_pdf_text(metadata["project_name"])

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
            continue
        metadata = (
            pdf_metadata_df.loc[pdf_metadata_df["pdf_filename"] == filename]
            .iloc[0]
            .to_dict()
        )
        try:
            # 1. Extraction texte brut
            raw_text: str = pymupdf4llm.to_markdown(
                folder_path / filename,
                header=False,
                footer=False,
                ignore_code=True,
                ignore_graphics=True,
                ignore_images=True,
            )  # type: ignore

            data = process_pdf_text(raw_text)
            data_project_name = process_pdf_text(metadata["project_name"])

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
        help="Path of the CSV file containing pdf metadata..",
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
        df = pl.read_parquet(pdf_path)

        process_all_pdfs_texts(df)
