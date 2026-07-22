from app.services.code_validation import validate_user_code


def test_rejects_file_and_process_capabilities():
    result = validate_user_code("import os\nopen('x')\n")
    assert not result["accepted"]
    assert not result["checks"]["Restricted imports and calls"]


def test_syntax_failure_does_not_submit_ready_result():
    result = validate_user_code("class UserStrategy(:\n")
    assert not result["accepted"]
    assert not result["checks"]["Python syntax"]
    assert result["errors"]
