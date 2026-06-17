import argparse
import json
import pprint
from datetime import datetime
from pathlib import Path

import polars as pl
from tqdm import tqdm

from .config import (
    MODELS_CONFIG,
    LABELS,
    LABELS_MAP,
    LLM_OUTPUT_JSON_SCHEMA,
)
from .lm_studio import get_model, run_inference
from .evaluation import compute_classification_metrics


def run_pdfs_inference(
    model_config: dict, pdf_df: pl.DataFrame, system_prompt: str
) -> pl.DataFrame:
    model = get_model(model_config["model_id"], model_config["model_config"])

    result = []
    for row in tqdm(
        pdf_df.iter_rows(named=True),
        desc=f"Predicting with {model_config['model_id']}",
        total=len(pdf_df),
    ):
        res_dict = run_inference(
            model,
            system_prompt=system_prompt,
            pdf_text=row["pdf_text"],
            response_format=LLM_OUTPUT_JSON_SCHEMA,
            labels=LABELS,
            labels_mapping=LABELS_MAP,
        )

        # Init true label matrix
        for label in LABELS:
            res_dict[LABELS_MAP[label]] = 1 if label in row["labels"] else 0

        res_dict["pdf_name"] = row["pdf_name"]
        result.append(res_dict)

    result_df = pl.DataFrame(result)

    model.unload()

    return result_df


def main():
    parser = argparse.ArgumentParser(description="LLM Zero-shot Land Classification")
    parser.add_argument(
        "pdf_path",
        type=Path,
        help="Path to the parquet file containing PDF preprocessing results",
    )

    parser.add_argument(
        "output_dir",
        type=Path,
        default="llm_results",
        help="Directory to save model results and classification reports",
    )

    parser.add_argument(
        "--models_ids",
        default=None,
        help="List of models to test (comma-separated), defaults to all if not specified",
    )

    parser.add_argument(
        "--no-auto-threshold",
        action="store_false",
        dest="auto_threshold",
        help="Disable automatic threshold selection (use fixed 0.5 by default)",
    )

    args = parser.parse_args()

    # Load system prompt
    system_prompt_path = Path(__file__).parent / "prompt_20260430.md"
    if not system_prompt_path.exists():
        raise FileNotFoundError(f"Prompt file not found at: {system_prompt_path}")
    system_prompt = system_prompt_path.read_text()

    models_to_test = (
        args.models_ids.split(",") if args.models_ids else MODELS_CONFIG.keys()
    )

    for model_id, config in MODELS_CONFIG.items():
        if model_id not in models_to_test:
            continue

        config["model_id"] = model_id
        # Create output subdirectory for this model
        model_out_dir = args.output_dir / model_id.replace("/", "_")
        if not model_out_dir.exists():
            model_out_dir.mkdir(parents=True)

        print(f"-------------{model_id}-------------")

        # Run inference and save results
        result_df = run_pdfs_inference(
            config, pl.read_parquet(args.pdf_path), system_prompt
        )
        timestamp = datetime.now().strftime("%Y_%m_%d_%H%M")
        output_file = model_out_dir / f"{timestamp}.parquet"
        result_df.write_parquet(output_file)

        # Compute and save classification report
        classification_report_dict = compute_classification_metrics(
            result_df, LABELS_MAP, auto_threshold=args.auto_threshold
        )

        output_report_file = model_out_dir / f"{timestamp}_report.json"
        pprint.pprint(classification_report_dict)
        with open(output_report_file, "w") as f:
            json.dump(classification_report_dict, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
