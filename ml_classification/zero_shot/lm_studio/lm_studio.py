import time
from typing import Any

import lmstudio as lms
from tqdm import tqdm


def get_model(model_id: str, model_config: dict) -> lms.LLM:
    llm_client = lms.get_default_client()
    model = llm_client.llm.load_new_instance(model_id, config=model_config)

    return model


def run_inference(
    model: lms.LLM,
    system_prompt: str,
    pdf_text: str,
    response_format: dict,
    labels: list[str],
    labels_mapping: dict[str, str],
) -> dict:
    chat = lms.Chat(system_prompt)
    chat.add_user_message(pdf_text)

    # Handle context overflow
    formatted = model.apply_prompt_template(chat)
    token_count = len(model.tokenize(formatted))
    while token_count + 1000 > model.get_context_length():
        pdf_text = pdf_text[: int(len(pdf_text) / 2)]
        chat = lms.Chat(system_prompt)
        chat.add_user_message(pdf_text)
        formatted = model.apply_prompt_template(chat)
        token_count = len(model.tokenize(formatted))

    start_time = time.time()

    with tqdm(
        total=100,
        desc="Processing PDF",
        unit="%",
        leave=False,
    ) as inf_bar:
        prediction = model.respond(
            chat,
            response_format=response_format,
            config={
                "temperature": 0.05,
                "maxTokens": 3000,
                "contextOverflowPolicy": "truncateMiddle",
            },
            on_prompt_processing_progress=(
                lambda progress: inf_bar.update(round(progress * 100, 2) - inf_bar.n)
            ),
        )

    total_time = time.time() - start_time

    res_dict: dict[str, None | Any] = {
        "contexts": None,
        "explanation": None,
        "prediction_time": None,
    }

    res_dict["prediction_time"] = total_time
    prediction_parsed = prediction.parsed
    if isinstance(prediction_parsed, dict):
        if not prediction.stats.stop_reason == "maxPredictedTokensReached":
            # Create predicted score matrix
            for label, score in prediction_parsed["scores"].items():  # type: ignore
                res_dict[labels_mapping[label] + "_score"] = score
            res_dict["contexts"] = prediction_parsed["contexts"]
            res_dict["explanation"] = prediction_parsed["explanation"]
    else:
        for label in labels_mapping:  # type: ignore
            res_dict[label + "_score"] = 0

    return res_dict
