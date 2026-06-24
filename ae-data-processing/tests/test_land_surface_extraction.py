import pytest
from extraction import (
    extract_max_land_surface,
)
from tests.config import EXPECTATIONS_FOLDER_PATH, SAMPLES_FOLDER_PATH

# ---------------------------------------------------------------------------
# extract_context tests
# ---------------------------------------------------------------------------


class TestLandSurfaceExtraction:
    """Tests for extraction of geographical data."""

    @pytest.mark.parametrize(
        "input_str,expected_land_surface",
        [
            ((EXPECTATIONS_FOLDER_PATH / "sample_1_context.md").read_text(), 43.0),
            ((EXPECTATIONS_FOLDER_PATH / "sample_2_context.md").read_text(), 5.9),
            ((EXPECTATIONS_FOLDER_PATH / "sample_3_context.md").read_text(), 18.6),
            ((SAMPLES_FOLDER_PATH / "sample_cas_par_cas_1.md").read_text(), 4.5),
        ],
    )
    def test_extract_land_surface(
        self,
        input_str: str,
        expected_land_surface: float,
    ):
        res = extract_max_land_surface(input_str)

        assert res == expected_land_surface

    @pytest.mark.parametrize(
        "input_str",
        [
            ((SAMPLES_FOLDER_PATH / "sample_absence_avis_1.md").read_text()),
            ((SAMPLES_FOLDER_PATH / "sample_absence_avis_2.md").read_text()),
            ((SAMPLES_FOLDER_PATH / "sample_cas_par_cas_2.md").read_text()),
        ],
    )
    def test_extract_land_surface_no_value(
        self,
        input_str: str,
    ):
        res = extract_max_land_surface(input_str)

        assert res is None
