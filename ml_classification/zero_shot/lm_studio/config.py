MODELS_CONFIG = {
    "mistralai/ministral-3-3b-instruct-2512": {
        "model_config": {
            "contextLength": 32768,
        },
    },
    "nvidia/nemotron-3-nano": {
        "model_config": {
            "contextLength": 32768,
        },
    },
    "euromoe-2.6b-a0.6b-instruct-2512": {
        "model_config": {
            "contextLength": 32768,
        },
    },
    "bartowski/meta-llama-3.1-8b-instruct": {
        "model_config": {
            "contextLength": 32768,
        },
    },
    "liquidai_lfm2-8b-a1b": {
        "model_config": {
            "contextLength": 32768,
        },
    },
    "lucie-7b-instruct-v1.1": {
        "model_config": {
            "contextLength": 22000,  # See model README
        },
    },
    "ministral-3-14b-instruct-2512": {
        "model_config": {
            "contextLength": 32768,
        },
    },
    "ministral-3-8b-instruct-2512": {
        "model_config": {
            "contextLength": 32768,
        },
    },
    "llama-3.2-3b-instruct": {
        "model_config": {
            "contextLength": 32768,
        },
    },
    "liquid/lfm2.5-1.2b": {
        "model_config": {
            "contextLength": 32768,
        },
    },
    "qwen/qwen3.5-9b": {
        "model_config": {
            "contextLength": 32768,
        },
    },
}

LLM_OUTPUT_JSON_SCHEMA = {
    "type": "object",
    "properties": {
        "scores": {
            "type": "object",
            "properties": {
                "Surfaces artificialisées": {"type": "number"},
                "Surfaces naturelles": {"type": "number"},
                "Surfaces agricoles": {"type": "number"},
                "Surfaces forestières": {"type": "number"},
            },
            "required": [
                "Surfaces artificialisées",
                "Surfaces naturelles",
                "Surfaces agricoles",
                "Surfaces forestières",
            ],
        },
        "contexts": {"type": "array", "items": {"type": "string"}},
        "explanation": {"type": "string"},
    },
    "required": ["scores", "contexts", "explanation"],
}

LABELS = [
    "Surfaces artificialisées",
    "Surfaces naturelles",
    "Surfaces agricoles",
    "Surfaces forestières",
]

LABELS_MAP = {
    "Surfaces artificialisées": "surfaces_artificialisees",
    "Surfaces naturelles": "surfaces_naturelles",
    "Surfaces agricoles": "surfaces_agricoles",
    "Surfaces forestières": "surfaces_forestieres",
}
