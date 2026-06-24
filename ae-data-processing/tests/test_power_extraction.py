import pytest
from extraction import (
    extract_max_power,
)
from tests.config import EXPECTATIONS_FOLDER_PATH, SAMPLES_FOLDER_PATH

# ---------------------------------------------------------------------------
# extract_context tests
# ---------------------------------------------------------------------------


class TestPowerExtraction:
    """Tests for extraction of geographical data."""

    @pytest.mark.parametrize(
        "input_str,expected_power",
        [
            ((EXPECTATIONS_FOLDER_PATH / "sample_1_context.md").read_text(), 12.0),
            ((EXPECTATIONS_FOLDER_PATH / "sample_2_context.md").read_text(), 2.9),
            ((EXPECTATIONS_FOLDER_PATH / "sample_3_context.md").read_text(), 6.72),
        ],
    )
    def test_extract_power_from_context(
        self,
        input_str: str,
        expected_power: float,
    ):
        res = extract_max_power(input_str)

        assert res == expected_power

    @pytest.mark.parametrize(
        "input_str",
        [
            ((SAMPLES_FOLDER_PATH / "sample_absence_avis_1.md").read_text()),
            ((SAMPLES_FOLDER_PATH / "sample_absence_avis_2.md").read_text()),
            ((SAMPLES_FOLDER_PATH / "sample_cas_par_cas_1.md").read_text()),
            ((SAMPLES_FOLDER_PATH / "sample_cas_par_cas_1.md").read_text()),
        ],
    )
    def test_extract_power_no_value(
        self,
        input_str: str,
    ):
        res = extract_max_power(input_str)

        assert res is None
