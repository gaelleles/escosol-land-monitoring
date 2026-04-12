import re

departement_code_and_commune_name_regex = re.compile(
    r"((?:à|communes? d(?:e|'|’)) *(?P<commune>[A-Za-zà-üÀ-Ü-,’' ]+))? +(?:\(?(?P<departement_code>[0-9AB]{2,5})\)?)"
)


def clean_departement_code(raw_departement_code: str) -> str | None:
    """Try to clean raw_departement_code to get consistent 2 to 3 digits departement format (3 digits for Overseas)"""
    if (len(raw_departement_code) == 2) or (len(raw_departement_code) == 3):
        return raw_departement_code

    if len(raw_departement_code) == 5:
        if ("A" in raw_departement_code) or ("B" in raw_departement_code):
            return raw_departement_code[:2]

        try:
            raw_departement_code_int = int(raw_departement_code)
        except Exception:
            return None

        if raw_departement_code_int > 97000:
            # Overseas case
            return raw_departement_code[:3]

        return raw_departement_code[:2]


def extract_departement_code_and_commune_name(
    string: str,
) -> tuple[str | None, str | None]:
    """Try to extract the commune name from a string like an AE document title"""
    commune_name = None
    departement_code = None
    match_o = re.finditer(
        departement_code_and_commune_name_regex,
        string,
    )
    if match_o is not None:
        commune_name_raw = match_o.group("commune")
        if commune_name_raw is not None:
            commune_name = commune_name_raw.strip()

        departement_code_raw = match_o.group("departement_code").strip()
        if departement_code_raw is not None:
            departement_code = clean_departement_code(departement_code_raw)

    return departement_code, commune_name
