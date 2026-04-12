import os
import re
from argparse import ArgumentParser
from pathlib import Path
from typing import Any

import marko
import pandas as pd
import polars as pl
import pymupdf
import pymupdf.layout  # noqa: F401
import pymupdf4llm
from tqdm import tqdm

# Code copied from the data4good sufficiency project
# https://github.com/dataforgoodfr/13_democratiser_sobriete
# Which covered similar issues of PDF text extraction

HEADERS = ["pdf_name", "land_surface_ha", "power_mwc"]


def get_raw_text_pymupdf(path: Path) -> str:
    """
    Extract raw text from a PDF using pymupdf.
    Much faster processing but lower-quality output compared to markdown.
    """
    with pymupdf.open(path) as doc:
        all_texts = [page.get_text() for page in doc]
        text = chr(12).join(all_texts)
        return text


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


def extraire_max_surface(text: str) -> float | None:
    ha = extraire_max_hectares(text)

    if ha:
        return ha

    m2 = extraire_max_m2(text)
    if m2:
        return m2 / 10000

    return None


def extraire_max_hectares(text) -> float | None:
    pattern = r"(\d{1,3}(?:[\s]\d{3})*(?:[.,]\d+)?)\s*(?:ha|hectares?)"

    matches = re.findall(pattern, text, re.IGNORECASE)

    if not matches:
        return None

    return process_matches(matches)


def extraire_max_m2(text) -> float | None:
    pattern = r"(\d{1,3}(?:[\s]\d{3})*(?:[.,]\d+)?)\s*(?:m2|m²)"

    matches = re.findall(pattern, text, re.IGNORECASE)

    if not matches:
        return None

    return process_matches(matches)


def extraire_max_mwc(text: str) -> float | None:
    pattern = (
        r"(\d{1,3}(?:[\s]\d{3})*(?:[.,]\d+)?)\s*(?:MWc|megawatt-crête|Méga Watt crête)"
    )

    matches = re.findall(pattern, text, re.IGNORECASE)

    if not matches:
        return None

    return process_matches(matches)


def extraire_max_kwc(text: str) -> float | None:
    pattern = r"(\d{1,3}(?:[\s]\d{3})*(?:[.,]\d+)?)\s*(?:KWc|kilowatt-crête)"

    matches = re.findall(pattern, text, re.IGNORECASE)

    if not matches:
        return None

    return process_matches(matches)


def extraire_max_wc(text: str) -> float | None:
    pattern = r"(\d{1,3}(?:[\s]\d{3})*(?:[.,]\d+)?)\s*(?:Wc)"

    matches = re.findall(pattern, text, re.IGNORECASE)

    if not matches:
        return None

    return process_matches(matches)


def extraire_max_power(text: str) -> float | None:
    mwc = extraire_max_mwc(text)

    if mwc:
        return mwc

    kwc = extraire_max_kwc(text)
    if kwc:
        return kwc / 1000

    wc = extraire_max_wc(text)
    if wc:
        return wc / 1000000

    return None


def process_matches(matches: list[Any]) -> float:
    valeurs = []
    for val in matches:
        val_propre = re.sub(r"\s+", "", val).replace(",", ".")
        valeurs.append(float(val_propre))

    return max(valeurs)


def process_pdf_text(text: str) -> dict[str, Any]:
    contexte = extract_context(text)

    ha = None
    mwc = None
    if contexte is not None:
        ha = extraire_max_surface(contexte)
        # Puissance
        mwc = extraire_max_power(contexte)

    if not ha:
        ha = extraire_max_surface(text)
    if not mwc:
        mwc = extraire_max_power(text)
    data = {
        "land_surface_ha": ha,
        "power_mwc": mwc,
    }

    return data


def process_all_pdfs_texts(pdf_df: pl.DataFrame):
    results = []
    for row in tqdm(pdf_df.iter_rows(named=True)):
        filename = row["pdf_name"]
        raw_text: str = row["pdf_text"]
        try:
            data = process_pdf_text(raw_text)

            results.append({"pdf_name": filename, **data})

        except Exception as e:
            print(f"Erreur sur {filename}: {e}")

    pd.DataFrame(results, columns=HEADERS).to_csv(
        output_path / "_pdf_extraction_results.csv", index=False
    )


def process_all_pdfs_files(folder_path: Path, output_path: Path):
    """
    Process all PDF files in the specified folder
    and extract land surface and power data then save it as a CSV file in output_path folder.
    """

    pdf_files = [f for f in os.listdir(folder_path) if f.lower().endswith(".pdf")]

    results = []
    for filename in tqdm(pdf_files):
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

            results.append({"pdf_name": filename, **data})

        except Exception as e:
            print(f"Erreur sur {filename}: {e}")

    pd.DataFrame(results, columns=HEADERS).to_csv(
        output_path / "_pdf_extraction_results.csv", index=False
    )


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        "pdf_to_data",
        description="Extract data from AE PDFs. Result is saved in a file pdf_extraction_result.csv.",
    )
    arg_parser.add_argument(
        "pdf_path",
        help="Path of the folder where are PDFs are located or path to a parquet dataset containing pdf_name and pdf_text columns.",
    )

    arg_parser.add_argument(
        "-o",
        "--output_path",
        help="Path of the folder where the CSV containing extracted data will be saved. Default to pdf_path.",
        dest="output_path",
    )

    args = arg_parser.parse_args()
    pdf_path = Path(args.pdf_path)

    if pdf_path.is_dir():
        output_path = pdf_path
        if args.output_path is not None:
            output_path = Path(args.output_path)
        process_all_pdfs_files(pdf_path, output_path)

    elif pdf_path.is_file():
        output_path = pdf_path.parent
        if args.output_path is not None:
            output_path = Path(args.output_path)
        df = pl.read_parquet(pdf_path)

        process_all_pdfs_texts(df)
