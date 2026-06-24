import re
from typing import Any

import spacy

nlp = spacy.load("fr_core_news_lg")

simple_commune_pattern = re.compile(
    r"(?:sur la )?commune d(?:e|'|’|u) ((?:L(?:es?|a) )?[a-z\-üàéèùâäëê]+)\b",
    flags=re.I,
)

multi_commune_pattern = re.compile(
    r"(?:sur les )?communes d(?:e|'|’|u) ((?:(?:(?:L(?:es?|a) )?[a-z'’\-üàéèùâäëê]+)(?:(?:, ?)|(?: et )))+(?:[a-z'’\-üàéèùâäëê]+))\b",
    flags=re.I,
)


def extract_presentation(text: str) -> str | None:
    presentation_regex = re.compile(r"pr(?:e|é)sentation du projet", flags=re.I)

    match_o = presentation_regex.search(text)

    if match_o is None:
        return None

    start_index = match_o.start(0)

    substring = text[start_index:]

    next_heading_index = substring.find("#")
    if next_heading_index != -1:
        substring = substring[:next_heading_index]

    return substring


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


def extract_communes_names_ml(text: str) -> list[str]:
    doc = nlp(text)

    communes = []
    for ent in doc.ents:
        if ent.label_ == "LOC":
            communes.append(ent.text)

    return communes


def extract_communes_names_regex(text: str) -> list[str]:
    communes_names = []

    match_o = simple_commune_pattern.search(text)
    if match_o is not None:
        communes_names.append(match_o.group(1))

    match_o = multi_commune_pattern.search(text)
    if match_o is not None:
        communes_raw_str = match_o.group(1)
        for commune_name in re.split(r", | et ", communes_raw_str):
            communes_names.append(commune_name)

    return communes_names


def extract_commune_and_departement(
    text: str,
) -> dict[str, str | None | list[str]]:
    dept_match = re.search(r"\(([0-9][0-9ABO]|[0-9]{3})\)", text)
    dept_number = None
    if dept_match:
        dept_number = dept_match.group(1).replace("O", "0")
        text = text[: dept_match.start()].strip()

    communes_names = []
    communes_names.extend(extract_communes_names_ml(text))
    communes_names.extend(extract_communes_names_regex(text))
    communes_names = list(set(communes_names))

    return {"departement_code": dept_number, "communes": communes_names}


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


def process_matches(matches: list[Any], max_val: float | None = None) -> float | None:
    valeurs = []
    for val in matches:
        val_propre = re.sub(r"\s+", "", val).replace(",", ".")
        valeurs.append(float(val_propre))

    if max_val:
        valeurs = [v for v in valeurs if v <= max_val]

    return max(valeurs, default=None)
