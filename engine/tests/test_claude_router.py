from nlp.claude_router import ALLOWED_NLQ_MODELS, _instruction_from_payload


def test_claude_payload_allowlists_models():
    instruction = _instruction_from_payload(
        {
            "models_to_run": ["greeks", "stress", "var"],
            "parameters": {},
            "topline_metric": "test",
            "explanation_request": "explain",
        }
    )
    assert instruction.models_to_run == ["greeks", "stress", "var"]


def test_claude_payload_keeps_supported_models():
    instruction = _instruction_from_payload(
        {
            "models_to_run": ["concentration", "sustainability"],
            "parameters": {},
            "topline_metric": "test",
            "explanation_request": "explain",
        }
    )
    assert instruction.models_to_run == ["concentration", "sustainability"]
    assert set(instruction.models_to_run) <= ALLOWED_NLQ_MODELS
