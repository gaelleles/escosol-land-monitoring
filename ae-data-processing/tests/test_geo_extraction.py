from typing import Any

import pytest
from extraction import (
    extract_commune_and_departement,
    extract_communes_names_ml,
    extract_communes_names_regex,
)
from tests.config import EXPECTATIONS_FOLDER_PATH, SAMPLES_FOLDER_PATH

# ---------------------------------------------------------------------------
# extract_context tests
# ---------------------------------------------------------------------------


class TestGeoExtraction:
    """Tests for extraction of geographical data."""

    @pytest.mark.parametrize(
        "input_str,expected_communes,expected_departement_code",
        [
            (
                (EXPECTATIONS_FOLDER_PATH / "sample_2_context.md").read_text(),
                ["Poët"],
                "05",
            ),
            (
                (SAMPLES_FOLDER_PATH / "sample_cas_par_cas_2.md").read_text(),
                ["Aubenas"],
                "07",
            ),
            (
                (SAMPLES_FOLDER_PATH / "sample_absence_avis_1.md").read_text(),
                ["Graissessac"],
                "34",
            ),
            (
                (SAMPLES_FOLDER_PATH / "sample_absence_avis_2.md").read_text(),
                ["Saisigne"],
                "11",
            ),
            (
                "Projet agrivoltaïque sur la commune de St-Bonnet-de-Bellac (87)",
                ["St-Bonnet-de-Bellac"],
                "87",
            ),
            (
                "Projet de création d’un parc photovoltaïque sur la commune de Leforest (62)",
                ["Leforest"],
                "62",
            ),
        ],
    )
    def test_extract_commune_name_and_departement(
        self,
        input_str: str,
        expected_communes: list[str],
        expected_departement_code: str,
    ):
        res = extract_commune_and_departement(input_str)

        assert res is not None
        assert "departement_code" in res.keys()
        assert "communes" in res.keys()

        assert res["communes"] is not None
        assert res["departement_code"] is not None

        assert all(e in res["communes"] for e in expected_communes)
        assert res["departement_code"] == expected_departement_code

    @pytest.mark.parametrize(
        "input_str,commune_name",
        [
            (
                (EXPECTATIONS_FOLDER_PATH / "sample_2_context.md").read_text(),
                "Poët",
            ),
            (
                (EXPECTATIONS_FOLDER_PATH / "sample_1_context.md").read_text(),
                "SAUCATS",
            ),
        ],
    )
    def test_extract_commune_name_ml(self, input_str: str, commune_name: str):
        res = extract_communes_names_ml(input_str)

        assert res is not None
        assert len(res) != 0
        assert commune_name in res

    @pytest.mark.parametrize(
        "input_str,commune_name",
        [
            (
                (EXPECTATIONS_FOLDER_PATH / "sample_2_context.md").read_text(),
                "Poët",
            ),
            (
                (EXPECTATIONS_FOLDER_PATH / "sample_1_context.md").read_text(),
                "SAUCATS",
            ),
        ],
    )
    def test_extract_commune_name_regex(self, input_str: str, commune_name: str):
        res = extract_communes_names_regex(input_str)

        assert res is not None
        assert len(res) != 0
        assert commune_name in res

    @pytest.mark.parametrize(
        "input_str,expected_communes",
        [
            (
                (EXPECTATIONS_FOLDER_PATH / "sample_1_context.md").read_text(),
                ["Saucats"],
            ),
            (
                (EXPECTATIONS_FOLDER_PATH / "sample_3_context.md").read_text(),
                ["Blond"],
            ),
            (
                (SAMPLES_FOLDER_PATH / "sample_cas_par_cas_1.md").read_text(),
                ["Sallaumines", "Avion"],
            ),
        ],
    )
    def test_extract_only_commune_name(
        self,
        input_str: str,
        expected_communes: list[str],
    ):
        res = extract_commune_and_departement(input_str)

        assert res is not None
        assert res["departement_code"] is None
        assert res["communes"] is not None

        assert all(e in res["communes"] for e in expected_communes)
