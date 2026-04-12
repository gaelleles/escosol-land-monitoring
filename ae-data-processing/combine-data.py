import re
from argparse import ArgumentParser
from pathlib import Path

import pandas as pd


def extract_data_title(text):
    # --- 1. EXTRACTION DU MOT "VOLTAÏQUE" ---
    type_match = re.search(r"\b\w*voltaï?que\w*\b", text, re.IGNORECASE)
    project_type = type_match.group(0) if type_match else None

    # --- 2. PUISSANCE (MWc) ---
    mwc_match = re.search(r"(\d+(?:[.,]\d+)?)\s*MWc?", text, re.IGNORECASE)
    mwc_val = mwc_match.group(1).replace(",", ".") if mwc_match else None

    # --- 3. SURFACE (Hectares) ---
    ha_match = re.search(r"(\d+(?:[.,]\d+)?)\s*(?:ha|hectares?)", text, re.IGNORECASE)
    ha_val = ha_match.group(1).replace(",", ".") if ha_match else None

    # --- 4. EXTRACTION DES COMMUNES ET DÉPARTEMENT ---
    text = text.strip().rstrip(".").replace('"', "").replace("« ", "").replace(" »", "")
    dept_match = re.search(r"\(?([0-9][0-9ABO]|[0-9]{3})\)?$", text)
    if not dept_match:
        return project_type, [], None, ha_val, mwc_val

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
        return project_type, [], dept, ha_val, mwc_val

    raw_names = content_before[last_pos:].strip()
    parts = re.split(r" et | & |,", raw_names)

    final_communes = []
    for p in parts:
        clean = re.sub(r'[«»"“”]', "", p).strip()
        clean = re.sub(r"^(de |d'|d’|le |la |les )", "", clean, flags=re.IGNORECASE)

        if any(char.isupper() for char in clean):
            final_communes.append(clean)

    return project_type, final_communes, dept, ha_val, mwc_val


if __name__ == "__main__":
    arg_parser = ArgumentParser(
        "combine-data",
        description="Combine all extracted data from Aes "
        "(either metadata or extracted PDF data in two files) "
        "in two files: combined_full_table.csv "
        "and combined_filtered_table.csv.",
    )
    arg_parser.add_argument(
        "csv_path",
        help="Path of the folder containing all previously created CSV files."
        "containing metadata and extracted PDFs data.",
    )
    arg_parser.add_argument(
        "-o",
        "-output_path",
        help="Path of the folder where to store combined_full_table.csv and combined_filtered_table.csv."
        "Default to csv_path.",
        dest="output_path",
    )
    args = arg_parser.parse_args()

    csv_path = Path(args.csv_path)
    output_path = csv_path
    if args.output_path:
        output_path = Path(args.output_path)

    communes = pd.read_csv(csv_path / "20230823-communes-departement-region.csv")
    ae_data = pd.read_csv(csv_path / "ae_year_links.csv")
    metadata = pd.read_csv(csv_path / "metadata_pdfs.csv")
    extracted_data = pd.read_csv(csv_path / "pdf_extraction_results.csv")

    merged_data = metadata.merge(
        ae_data[["year_url", "region", "year"]], on="year_url", how="left"
    ).merge(extracted_data, on="pdf_name", how="left")

    (
        merged_data["project_type"],
        merged_data["nom_commune"],
        merged_data["dept"],
        merged_data["land_surface_ha_title"],
        merged_data["power_mwc_title"],
    ) = zip(*merged_data["title"].apply(extract_data_title))

    # Certains projets ont plusieurs communes, on fait
    # une ligne = une commune même si ça multiplie les lignes
    merged_data = merged_data.explode("nom_commune")
    merged_data["nom_commune"] = merged_data["nom_commune"].str.strip()

    communes["dept"] = communes["code_departement"].apply(lambda x: str(x).zfill(2))
    communes["nom_commune"] = communes["nom_commune"].str.strip()

    full_table = merged_data.merge(
        communes[["nom_commune", "dept", "longitude", "latitude"]],
        on=["nom_commune", "dept"],
        how="left",
    )

    # Les données hectares et MWc extraites du titre ont priorité
    # sur celles extraites du contenu
    full_table["power_mwc"] = full_table.apply(
        lambda row: row["power_mwc_title"]
        if pd.notnull(row["power_mwc_title"])
        else row["power_mwc"],
        axis=1,
    )
    full_table["land_surface_ha"] = full_table.apply(
        lambda row: row["land_surface_ha_title"]
        if pd.notnull(row["land_surface_ha_title"])
        else row["land_surface_ha"],
        axis=1,
    )

    # En l'état, pdf name fait office d'ID unique pour chaque projet
    filtered_table = full_table[
        [
            "pdf_name",
            "year",
            "region",
            "project_type",
            "nom_commune",
            "dept",
            "land_surface_ha",
            "power_mwc",
            "longitude",
            "latitude",
        ]
    ]

    full_table.to_csv(output_path / "combined_full_table.csv", index=False)
    filtered_table.to_csv(output_path / "combined_filtered_table.csv", index=False)
