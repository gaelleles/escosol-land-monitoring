import logging
import urllib
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEPARTEMENTS_MAP = pd.read_csv(Path(__file__).parent / "v_departement_2025.csv")


def get_scraped_avis_dict(
    project_name: str | None,
    communes_names: list[str] | None,
    departement_name: str | None,
    project_date: datetime | None,
    pdf_filename: str | None,
    pdf_url: str | None,
) -> dict[str, Any]:
    departement_code_insee = None
    if departement_name is not None:
        try:
            departement_code_insee = DEPARTEMENTS_MAP.loc[
                DEPARTEMENTS_MAP["LIBELLE"].str.replace("-", " ")
                == departement_name.replace("-", " ")
            ].iloc[0]["DEP"]
        except Exception as exc:
            logger.debug("Departement with name %s not found.", departement_name, exc)

    pdf_prefix = urllib.parse.urlparse(pdf_url).netloc
    pdf_filename = pdf_prefix + "_" + pdf_filename

    return {
        "project_name": project_name.strip(),
        "communes_names_scraped": communes_names,
        "departement_name_scraped": departement_name,
        "departement_code_insee_scraped": departement_code_insee,
        "date_scraped": project_date,
        "pdf_filename": pdf_filename,
        "pdf_url": pdf_url,
    }
