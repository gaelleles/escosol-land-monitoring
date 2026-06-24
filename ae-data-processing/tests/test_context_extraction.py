import pytest
from extraction import extract_presentation
from tests.config import EXPECTATIONS_FOLDER_PATH, SAMPLES_FOLDER_PATH

# ---------------------------------------------------------------------------
# extract_context tests
# ---------------------------------------------------------------------------


class TestExtractContext:
    """Tests for extract_presentation – extracts a section from markdown headings."""

    @pytest.mark.parametrize(
        "input_str,expected_str",
        [
            (
                (SAMPLES_FOLDER_PATH / "sample_1.md").read_text(),
                (EXPECTATIONS_FOLDER_PATH / "sample_1_context.md").read_text(),
            ),
            (
                (SAMPLES_FOLDER_PATH / "sample_2.md").read_text(),
                (EXPECTATIONS_FOLDER_PATH / "sample_2_context.md").read_text(),
            ),
            (
                (SAMPLES_FOLDER_PATH / "sample_3.md").read_text(),
                (EXPECTATIONS_FOLDER_PATH / "sample_3_context.md").read_text(),
            ),
        ],
    )
    def test_extract_presentation(self, input_str: str, expected_str: str):
        """Extract content under a 'Présentation du projet' heading."""
        text = input_str
        result = extract_presentation(text)

        assert result is not None
        assert result.strip() == expected_str.strip()

    @pytest.mark.parametrize(
        "input_str",
        [
            (SAMPLES_FOLDER_PATH / "sample_cas_par_cas_1.md").read_text(),
            (SAMPLES_FOLDER_PATH / "sample_cas_par_cas_2.md").read_text(),
            (SAMPLES_FOLDER_PATH / "sample_absence_avis_1.md").read_text(),
            (SAMPLES_FOLDER_PATH / "sample_absence_avis_2.md").read_text(),
        ],
    )
    def test_no_context(self, input_str: str):
        """Extract content under a 'Présentation du projet' heading."""
        text = input_str
        result = extract_presentation(text)

        assert result is None
