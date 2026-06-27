"""Tests de la classification ENAF (``enaf.classer_enaf``).

Purement en mémoire : aucune base de données ni dépendance géospatiale requise.
"""

import pytest

from enaf import (
    DEFAUT,
    SURFACES_AGRICOLES,
    SURFACES_ARTIFICIALISEES,
    SURFACES_FORESTIERES,
    SURFACES_FRICHES,
    SURFACES_NATURELLES,
    classer_enaf,
)


class TestClasserEnaf:
    @pytest.mark.parametrize(
        "code_us,attendu",
        [
            ("US1.1", SURFACES_AGRICOLES),
            ("US1.5", SURFACES_AGRICOLES),
            ("US1.2", SURFACES_FORESTIERES),
            ("US1.4", SURFACES_NATURELLES),
            ("US2", SURFACES_ARTIFICIALISEES),
            ("US3", SURFACES_ARTIFICIALISEES),
            ("US4.1.1", SURFACES_ARTIFICIALISEES),
            ("US5", SURFACES_ARTIFICIALISEES),
            ("US6.2", SURFACES_FRICHES),
            ("US6.3", SURFACES_NATURELLES),
        ],
    )
    def test_code_us(self, code_us, attendu):
        assert classer_enaf(code_us) == attendu

    def test_normalisation_casse_et_espaces(self):
        assert classer_enaf("  us1.1 ") == SURFACES_AGRICOLES

    @pytest.mark.parametrize("code_us", [None, "", "US9.9", "inconnu"])
    def test_code_absent_ou_inconnu_donne_le_defaut(self, code_us):
        assert classer_enaf(code_us) == DEFAUT

    def test_code_cs_ligneux_affine_naturel_en_forestier(self):
        # US6.3 (sans usage) → naturel, mais couverture arborée → forestier.
        assert classer_enaf("US6.3", code_cs="CS1.1.1.1") == SURFACES_FORESTIERES

    def test_code_cs_n_affecte_pas_les_categories_non_naturelles(self):
        # Un verger (agricole) sur couverture arborée reste agricole.
        assert classer_enaf("US1.1", code_cs="CS1.1.1.1") == SURFACES_AGRICOLES

    @pytest.mark.parametrize("artif", [True, "Artificialisé", "oui", "1"])
    def test_marqueur_artificialise_est_prioritaire(self, artif):
        # Quel que soit le code d'usage, le marqueur artif l'emporte.
        assert classer_enaf("US1.1", artif=artif) == SURFACES_ARTIFICIALISEES

    @pytest.mark.parametrize("artif", [False, "Non artificialisé", None])
    def test_marqueur_non_artificialise_n_a_pas_d_effet(self, artif):
        assert classer_enaf("US1.1", artif=artif) == SURFACES_AGRICOLES
