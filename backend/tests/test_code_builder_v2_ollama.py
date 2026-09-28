from code_builder_v2.models import TaskRequest
from code_builder_v2.ollama import OllamaChangeGenerator, OllamaClient, OllamaPlanner, OllamaError, JSONRecoveryError, RateLimitError, _extract_json_object
from code_builder_v2.models import GenerationProgress


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def generate_json(self, prompt, model=None, progress: GenerationProgress | None = None):
        return self.responses.pop(0)


class FakeClientWithRetry:
    """Fake client that fails first N times then succeeds."""
    def __init__(self, fail_responses, success_response):
        self.fail_responses = list(fail_responses)
        self.success_response = success_response
        self.call_count = 0

    def generate_json(self, prompt, model=None, progress: GenerationProgress | None = None):
        self.call_count += 1
        if self.fail_responses:
            raise OllamaError(self.fail_responses.pop(0))
        return self.success_response


def test_ollama_planner_parses_structured_plan():
    client = FakeClient([{"summary":"x","changes":[{"path":"a.py","operation":"create","reason":"needed"}],"validation_commands":["pytest -q"]}])
    plan = OllamaPlanner(client).create_plan(TaskRequest(prompt="create a.py"))
    assert plan.changes[0].path == "a.py"


def test_planner_requests_executable_validation_commands_only():
    class CapturingClient:
        prompt = ""

        def generate_json(self, prompt, model=None):
            self.prompt = prompt
            return {"summary": "x", "changes": [], "validation_commands": []}

    client = CapturingClient()
    OllamaPlanner(client).create_plan(TaskRequest(prompt="Create index.html"))
    assert 'Never put manual instructions such as "Open index.html in a browser"' in client.prompt
    assert "return an empty list" in client.prompt


def test_ollama_generator_returns_full_file_changes():
    client = FakeClient([{"changes":[{"path":"a.py","operation":"create","content":"x = 1\n"}]}])
    planner = OllamaPlanner(FakeClient([{"summary":"x","changes":[{"path":"a.py","operation":"create","reason":"needed"}],"validation_commands":[]}]))
    request = TaskRequest(prompt="create a.py")
    plan = planner.create_plan(request)
    changes = OllamaChangeGenerator(client).generate(request, plan, {})
    assert changes[0].content == "x = 1\n"


def test_cloud_code_model_defaults_to_verified_shared_groq_model(monkeypatch):
    monkeypatch.delenv("GROQ_CODE_MODEL", raising=False)
    monkeypatch.setenv("LUMINA_GROQ_MODEL", "openai/gpt-oss-120b")
    assert OllamaClient()._groq_model("qwen2.5-coder:7b") == "openai/gpt-oss-120b"


def test_cloud_code_model_explicit_override_takes_precedence(monkeypatch):
    monkeypatch.setenv("GROQ_CODE_MODEL", "openai/gpt-oss-20b")
    assert OllamaClient()._groq_model("qwen2.5-coder:7b") == "openai/gpt-oss-20b"


def test_extract_json_object_handles_truncated_json():
    """Test that _extract_json_object handles truncated/malformed JSON."""
    # Valid JSON
    assert _extract_json_object('{"key": "value"}') == {"key": "value"}
    
    # JSON with markdown fences
    assert _extract_json_object('```json\n{"key": "value"}\n```') == {"key": "value"}
    
    # JSON embedded in text
    assert _extract_json_object('Some text {"key": "value"} more text') == {"key": "value"}
    
    # Truncated JSON (missing closing brace)
    truncated = '{"changes": [{"path": "a.py", "operation": "create", "content": "x = 1'
    try:
        _extract_json_object(truncated)
        assert False, "Should have raised OllamaError"
    except OllamaError:
        pass  # Expected


def test_json_recovery_prompt_contains_original_request():
    """Test that the recovery prompt preserves the original request."""
    from code_builder_v2.ollama import _build_json_recovery_prompt
    
    original = "Create a multi-file React app"
    failed = '{"changes": [{"path": "App.jsx", "operation": "create", "content": "import React'
    
    recovery = _build_json_recovery_prompt(original, failed, 0)
    
    assert original in recovery
    assert "truncated" in recovery.lower() or "malformed" in recovery.lower()
    assert "complete valid JSON" in recovery


def test_generate_json_fallback_chain(monkeypatch):
    """Test that generate_json falls back through providers on failure."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("HF_TOKEN", "fake-token")
    monkeypatch.setenv("LUMINA_USE_LOCAL_OLLAMA", "true")  # Enable local Ollama for this test
    
    client = OllamaClient()
    
    # Mock the provider methods to simulate failures then success
    call_order = []
    
    def mock_groq(self, prompt, model=None):
        call_order.append("groq")
        raise JSONRecoveryError("Groq JSON recovery exhausted")
    
    def mock_hf(self, prompt, model=None):
        call_order.append("huggingface")
        raise OllamaError("HF failed")
    
    def mock_ollama(self, prompt, model=None):
        call_order.append("ollama")
        return {"result": "success"}
    
    monkeypatch.setattr(OllamaClient, "_generate_with_groq", mock_groq)
    monkeypatch.setattr(OllamaClient, "_generate_with_huggingface", mock_hf)
    monkeypatch.setattr(OllamaClient, "_generate_with_local_ollama", mock_ollama)
    
    result = client.generate_json("test prompt")
    
    assert result == {"result": "success"}
    assert call_order == ["groq", "huggingface", "ollama"]


def test_generate_json_succeeds_on_first_provider(monkeypatch):
    """Test that generate_json succeeds on first provider without fallback."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("HF_TOKEN", "fake-token")
    
    client = OllamaClient()
    
    def mock_groq(self, prompt, model=None):
        return {"result": "success"}
    
    def mock_hf(self, prompt, model=None):
        raise AssertionError("Should not fall back to HF")
    
    def mock_ollama(self, prompt, model=None):
        raise AssertionError("Should not fall back to Ollama")
    
    monkeypatch.setattr(OllamaClient, "_generate_with_groq", mock_groq)
    monkeypatch.setattr(OllamaClient, "_generate_with_huggingface", mock_hf)
    monkeypatch.setattr(OllamaClient, "_generate_with_local_ollama", mock_ollama)
    
    result = client.generate_json("test prompt")
    
    assert result == {"result": "success"}


def test_generate_json_no_providers_raises(monkeypatch):
    """Test that generate_json raises when no providers configured."""
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("HUGGINGFACEHUB_API_TOKEN", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("LUMINA_USE_LOCAL_OLLAMA", raising=False)
    
    client = OllamaClient()
    
    try:
        client.generate_json("test prompt")
        assert False, "Should have raised"
    except OllamaError as e:
        assert "No model providers configured" in str(e)


def test_generate_json_production_uses_cloud_only(monkeypatch):
    """Test that production (no local Ollama) uses only cloud providers."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("HF_TOKEN", "fake-token")
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    monkeypatch.delenv("LUMINA_USE_LOCAL_OLLAMA", raising=False)
    
    client = OllamaClient()
    
    call_order = []
    
    def mock_groq(self, prompt, model=None):
        call_order.append("groq")
        raise JSONRecoveryError("Groq JSON recovery exhausted")
    
    def mock_hf(self, prompt, model=None):
        call_order.append("huggingface")
        return {"result": "success"}
    
    def mock_ollama(self, prompt, model=None):
        call_order.append("ollama")
        return {"result": "should not be called"}
    
    monkeypatch.setattr(OllamaClient, "_generate_with_groq", mock_groq)
    monkeypatch.setattr(OllamaClient, "_generate_with_huggingface", mock_hf)
    monkeypatch.setattr(OllamaClient, "_generate_with_local_ollama", mock_ollama)
    
    result = client.generate_json("test prompt")
    
    assert result == {"result": "success"}
    # Should NOT call ollama in production
    assert call_order == ["groq", "huggingface"]
    assert "ollama" not in call_order


def test_generate_json_local_ollama_enabled(monkeypatch):
    """Test that local Ollama is used when LUMINA_USE_LOCAL_OLLAMA=true."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("LUMINA_USE_LOCAL_OLLAMA", "true")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("OLLAMA_BASE_URL", raising=False)
    
    client = OllamaClient()
    
    call_order = []
    
    def mock_groq(self, prompt, model=None):
        call_order.append("groq")
        raise JSONRecoveryError("Groq JSON recovery exhausted")
    
    def mock_ollama(self, prompt, model=None):
        call_order.append("ollama")
        return {"result": "success"}
    
    monkeypatch.setattr(OllamaClient, "_generate_with_groq", mock_groq)
    monkeypatch.setattr(OllamaClient, "_generate_with_local_ollama", mock_ollama)
    
    result = client.generate_json("test prompt")
    
    assert result == {"result": "success"}
    assert call_order == ["groq", "ollama"]


def test_generate_json_production_ollama_endpoint(monkeypatch):
    """Test that production Ollama endpoint is used when OLLAMA_BASE_URL is configured."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("OLLAMA_BASE_URL", "https://ollama.example.com")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("LUMINA_USE_LOCAL_OLLAMA", raising=False)
    
    client = OllamaClient()
    
    call_order = []
    
    def mock_groq(self, prompt, model=None):
        call_order.append("groq")
        raise JSONRecoveryError("Groq JSON recovery exhausted")
    
    def mock_ollama(self, prompt, model=None):
        call_order.append("ollama")
        # Verify the base_url was updated
        assert self.base_url == "https://ollama.example.com"
        return {"result": "success"}
    
    monkeypatch.setattr(OllamaClient, "_generate_with_groq", mock_groq)
    monkeypatch.setattr(OllamaClient, "_generate_with_local_ollama", mock_ollama)
    
    result = client.generate_json("test prompt")
    
    assert result == {"result": "success"}
    assert call_order == ["groq", "ollama"]
    assert client.base_url == "https://ollama.example.com"


def test_generate_json_localhost_ollama_not_used_in_production(monkeypatch):
    """Test that localhost Ollama is NOT used as production fallback."""
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
    monkeypatch.delenv("HF_TOKEN", raising=False)
    monkeypatch.delenv("LUMINA_USE_LOCAL_OLLAMA", raising=False)
    
    client = OllamaClient()
    
    call_order = []
    
    def mock_groq(self, prompt, model=None):
        call_order.append("groq")
        raise JSONRecoveryError("Groq JSON recovery exhausted")
    
    def mock_ollama(self, prompt, model=None):
        call_order.append("ollama")
        return {"result": "should not be called"}
    
    monkeypatch.setattr(OllamaClient, "_generate_with_groq", mock_groq)
    monkeypatch.setattr(OllamaClient, "_generate_with_local_ollama", mock_ollama)
    
    # Should raise because Groq fails and no other providers are available
    # (localhost Ollama is not included in production chain)
    try:
        client.generate_json("test prompt")
        assert False, "Should have raised"
    except OllamaError as e:
        assert "All providers failed" in str(e)
    assert call_order == ["groq"]
    assert "ollama" not in call_order


def test_validate_changes_schema_accepts_valid_changes():
    """Test that _validate_changes_schema accepts valid changes."""
    from code_builder_v2.ollama import _validate_changes_schema
    import logging
    
    log = logging.getLogger("test")
    
    # Valid create
    valid, error = _validate_changes_schema({
        "changes": [{"path": "a.py", "operation": "create", "content": "x = 1"}]
    }, log)
    assert valid is True
    assert error == ""
    
    # Valid update
    valid, error = _validate_changes_schema({
        "changes": [{"path": "a.py", "operation": "update", "content": "x = 2"}]
    }, log)
    assert valid is True
    
    # Valid delete
    valid, error = _validate_changes_schema({
        "changes": [{"path": "a.py", "operation": "delete", "content": None}]
    }, log)
    assert valid is True
    
    # Multiple valid changes
    valid, error = _validate_changes_schema({
        "changes": [
            {"path": "a.py", "operation": "create", "content": "x = 1"},
            {"path": "b.py", "operation": "update", "content": "y = 2"},
            {"path": "c.py", "operation": "delete", "content": None}
        ]
    }, log)
    assert valid is True


def test_validate_changes_schema_rejects_strings_in_changes():
    """Test that _validate_changes_schema rejects strings in changes array."""
    from code_builder_v2.ollama import _validate_changes_schema
    import logging
    
    log = logging.getLogger("test")
    
    # String instead of object
    valid, error = _validate_changes_schema({
        "changes": ["not an object"]
    }, log)
    assert valid is False
    assert "must be an object" in error


def test_validate_changes_schema_rejects_nested_arrays():
    """Test that _validate_changes_schema rejects nested arrays in changes."""
    from code_builder_v2.ollama import _validate_changes_schema
    import logging
    
    log = logging.getLogger("test")
    
    # Nested array
    valid, error = _validate_changes_schema({
        "changes": [[{"path": "a.py", "operation": "create", "content": "x = 1"}]]
    }, log)
    assert valid is False
    assert "must be an object" in error


def test_validate_changes_schema_rejects_missing_fields():
    """Test that _validate_changes_schema rejects missing required fields."""
    from code_builder_v2.ollama import _validate_changes_schema
    import logging
    
    log = logging.getLogger("test")
    
    # Missing path
    valid, error = _validate_changes_schema({
        "changes": [{"operation": "create", "content": "x = 1"}]
    }, log)
    assert valid is False
    assert "path" in error
    
    # Missing operation
    valid, error = _validate_changes_schema({
        "changes": [{"path": "a.py", "content": "x = 1"}]
    }, log)
    assert valid is False
    assert "operation" in error
    
    # Invalid operation
    valid, error = _validate_changes_schema({
        "changes": [{"path": "a.py", "operation": "invalid", "content": "x = 1"}]
    }, log)
    assert valid is False
    assert "operation" in error
    
    # Missing content
    valid, error = _validate_changes_schema({
        "changes": [{"path": "a.py", "operation": "create"}]
    }, log)
    assert valid is False
    assert "content" in error
    
    # None content for create
    valid, error = _validate_changes_schema({
        "changes": [{"path": "a.py", "operation": "create", "content": None}]
    }, log)
    assert valid is False
    assert "content" in error
    
    # Non-null content for delete
    valid, error = _validate_changes_schema({
        "changes": [{"path": "a.py", "operation": "delete", "content": "should be null"}]
    }, log)
    assert valid is False
    assert "content" in error


def test_validate_changes_schema_rejects_empty_changes():
    """Test that _validate_changes_schema rejects empty changes array."""
    from code_builder_v2.ollama import _validate_changes_schema
    import logging
    
    log = logging.getLogger("test")
    
    valid, error = _validate_changes_schema({
        "changes": []
    }, log)
    assert valid is False
    assert "empty" in error
    
    # Missing changes key
    valid, error = _validate_changes_schema({
        "other": "data"
    }, log)
    assert valid is False
    assert "changes" in error
    
    # Changes not an array
    valid, error = _validate_changes_schema({
        "changes": "not an array"
    }, log)
    assert valid is False
    assert "array" in error


def test_schema_recovery_prompt_contains_schema_error(monkeypatch):
    """Test that the schema recovery prompt includes the schema error."""
    from code_builder_v2.ollama import _build_schema_recovery_prompt
    
    original = "Create a React app"
    failed = '{"changes": ["not an object"]}'
    schema_error = "changes[0] must be an object, got str"
    
    recovery = _build_schema_recovery_prompt(original, failed, schema_error, 0)
    
    assert original in recovery
    assert schema_error in recovery
    assert "changes" in recovery
    assert "create|update|delete" in recovery
    assert "MUST be an array of objects" in recovery


def test_ollama_generator_schema_recovery(monkeypatch):
    """Test that OllamaChangeGenerator retries on schema-invalid output."""
    from code_builder_v2.models import TaskRequest, ChangePlan, PlannedChange
    
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("LUMINA_USE_LOCAL_OLLAMA", "true")
    
    # First response has invalid schema (strings in changes), second is valid
    responses = [
        {"changes": ["invalid", "also invalid"]},  # Schema invalid
        {"changes": [{"path": "a.py", "operation": "create", "content": "x = 1"}]}  # Valid
    ]
    
    call_count = [0]
    
    def mock_generate_json(self, prompt, model=None, progress=None):
        call_count[0] += 1
        return responses.pop(0)
    
    monkeypatch.setattr(OllamaClient, "generate_json", mock_generate_json)
    
    client = OllamaClient()
    generator = OllamaChangeGenerator(client)
    
    plan = ChangePlan(
        summary="Create app",
        changes=[PlannedChange(path="a.py", operation="create", reason="needed")],
        validation_commands=[]
    )
    request = TaskRequest(prompt="create a.py")
    
    changes = generator.generate(request, plan, {})
    
    # Should have retried once and succeeded
    assert call_count[0] == 2
    assert len(changes) == 1
    assert changes[0].path == "a.py"
    assert changes[0].content == "x = 1"


def test_ollama_generator_schema_fallback_after_retries(monkeypatch):
    """Test that schema validation failure falls back to next provider after retries."""
    from code_builder_v2.models import TaskRequest, ChangePlan, PlannedChange
    
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("HF_TOKEN", "fake-token")
    monkeypatch.setenv("LUMINA_USE_LOCAL_OLLAMA", "true")
    
    call_order = []
    
    def mock_groq(self, prompt, model=None):
        call_order.append("groq")
        # Always return schema-invalid response
        raise JSONRecoveryError("Schema validation failed after 3 attempts")
    
    def mock_hf(self, prompt, model=None):
        call_order.append("huggingface")
        return {"changes": [{"path": "a.py", "operation": "create", "content": "x = 1"}]}
    
    def mock_ollama(self, prompt, model=None):
        call_order.append("ollama")
        return {"changes": [{"path": "b.py", "operation": "create", "content": "y = 2"}]}
    
    monkeypatch.setattr(OllamaClient, "_generate_with_groq", mock_groq)
    monkeypatch.setattr(OllamaClient, "_generate_with_huggingface", mock_hf)
    monkeypatch.setattr(OllamaClient, "_generate_with_local_ollama", mock_ollama)
    
    client = OllamaClient()
    generator = OllamaChangeGenerator(client)
    
    plan = ChangePlan(
        summary="Create app",
        changes=[PlannedChange(path="a.py", operation="create", reason="needed")],
        validation_commands=[]
    )
    request = TaskRequest(prompt="create a.py")
    
    changes = generator.generate(request, plan, {})
    

# HF unsupported task error test
def test_ollama_generator_hf_unsupported_task_fallback(monkeypatch):
    """Test that HF 'task not supported' error falls back to next provider immediately."""
    from code_builder_v2.models import TaskRequest, ChangePlan, PlannedChange
    from code_builder_v2.ollama import OllamaError
    
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("HF_TOKEN", "fake-token")
    monkeypatch.setenv("LUMINA_USE_LOCAL_OLLAMA", "true")
    
    call_order = []
    
    def mock_groq(self, prompt, model=None):
        call_order.append("groq")
        raise OllamaError("Groq API error")
    
    def mock_hf(self, prompt, model=None):
        call_order.append("huggingface")
        # Simulate the nscale "task not supported" error
        raise OllamaError("Task 'text-generation' not supported by provider nscale")
    
    def mock_ollama(self, prompt, model=None):
        call_order.append("ollama")
        return {"changes": [{"path": "a.py", "operation": "create", "content": "x = 1"}]}
    
    monkeypatch.setattr(OllamaClient, "_generate_with_groq", mock_groq)
    monkeypatch.setattr(OllamaClient, "_generate_with_huggingface", mock_hf)
    monkeypatch.setattr(OllamaClient, "_generate_with_local_ollama", mock_ollama)
    
    client = OllamaClient()
    generator = OllamaChangeGenerator(client)
    
    plan = ChangePlan(
        summary="Create app",
        changes=[PlannedChange(path="a.py", operation="create", reason="needed")],
        validation_commands=[]
    )
    request = TaskRequest(prompt="create a.py")
    
    changes = generator.generate(request, plan, {})
    
    # Should fall back to ollama after HF unsupported task error
    assert len(changes) == 1
    assert changes[0].path == "a.py"
    assert "groq" in call_order
    assert "huggingface" in call_order
    assert "ollama" in call_order


def test_ollama_generator_incremental_multi_file(monkeypatch):
    """Test that multi-file applications are generated incrementally (one file per call)."""
    from code_builder_v2.models import TaskRequest, ChangePlan, PlannedChange
    
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("LUMINA_USE_LOCAL_OLLAMA", "true")
    
    # Track how many times generate_json is called
    call_count = [0]
    
    def mock_generate_json(self, prompt, model=None, progress=None):
        call_count[0] += 1
        # Each call should return a single file change
        file_idx = call_count[0] - 1
        return {"changes": [{
            "path": f"file{file_idx}.py",
            "operation": "create",
            "content": f"# File {file_idx}\nvalue = {file_idx}\n"
        }]}
    
    monkeypatch.setattr(OllamaClient, "generate_json", mock_generate_json)
    
    client = OllamaClient()
    generator = OllamaChangeGenerator(client)
    
    # Plan with 3 files - should trigger incremental generation
    plan = ChangePlan(
        summary="Create multi-file app",
        changes=[
            PlannedChange(path="file0.py", operation="create", reason="first"),
            PlannedChange(path="file1.py", operation="create", reason="second"),
            PlannedChange(path="file2.py", operation="create", reason="third"),
        ],
        validation_commands=[]
    )
    request = TaskRequest(prompt="create 3 files")
    
    changes = generator.generate(request, plan, {})
    
    # Should have called generate_json 3 times (once per file)
    assert call_count[0] == 3
    assert len(changes) == 3
    assert changes[0].path == "file0.py"
    assert changes[1].path == "file1.py"
    assert changes[2].path == "file2.py"


def test_ollama_generator_incremental_failed_file_retry(monkeypatch):
    """Test that a failed file can be retried without regenerating completed files."""
    from code_builder_v2.models import TaskRequest, ChangePlan, PlannedChange
    from code_builder_v2.ollama import OllamaError, JSONRecoveryError, RateLimitError
    
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("LUMINA_USE_LOCAL_OLLAMA", "true")
    
    # Track call sequence
    call_log = []
    
    def mock_generate_json(self, prompt, model=None, progress=None):
        call_log.append(prompt)
        # Check for the specific file being generated in the prompt
        if '"path": "file0.py"' in prompt or 'file0.py' in prompt and 'file1.py' not in prompt:
            return {"changes": [{
                "path": "file0.py",
                "operation": "create",
                "content": "# File 0\nvalue = 0\n"
            }]}
        elif '"path": "file1.py"' in prompt or ('file1.py' in prompt and 'file2.py' not in prompt and 'file0.py' not in prompt):
            return {"changes": [{
                "path": "file1.py",
                "operation": "create",
                "content": "# File 1\nvalue = 1\n"
            }]}
        elif '"path": "file2.py"' in prompt:
            # Fail on third file - simulate rate limit
            raise RateLimitError("Rate limit exceeded", provider="groq", model="test")
        return {"changes": []}
    
    monkeypatch.setattr(OllamaClient, "generate_json", mock_generate_json)
    
    client = OllamaClient()
    generator = OllamaChangeGenerator(client)
    
    plan = ChangePlan(
        summary="Create multi-file app",
        changes=[
            PlannedChange(path="file0.py", operation="create", reason="first"),
            PlannedChange(path="file1.py", operation="create", reason="second"),
            PlannedChange(path="file2.py", operation="create", reason="third"),
        ],
        validation_commands=[]
    )
    request = TaskRequest(prompt="create 3 files")
    
    # Should fail on third file
    try:
        generator.generate(request, plan, {})
        assert False, "Should have raised RateLimitError"
    except RateLimitError:
        pass
    
    # Verify first two files were generated (calls made for file0 and file1)
    file0_calls = sum(1 for p in call_log if 'file0.py' in p and 'file1.py' not in p)
    file1_calls = sum(1 for p in call_log if 'file1.py' in p and 'file2.py' not in p)
    file2_calls = sum(1 for p in call_log if 'file2.py' in p)
    
    # Each file should be attempted at least once
    assert file0_calls >= 1
    assert file1_calls >= 1
    assert file2_calls >= 1


def test_ollama_generator_fast_path_for_small_apps(monkeypatch):
    """Test that small applications (1-2 files) use fast path (single call)."""
    from code_builder_v2.models import TaskRequest, ChangePlan, PlannedChange
    
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("LUMINA_USE_LOCAL_OLLAMA", "true")
    
    call_count = [0]
    
    def mock_generate_json(self, prompt, model=None, progress=None):
        call_count[0] += 1
        # Return all files in one response (fast path)
        return {"changes": [
            {"path": "a.py", "operation": "create", "content": "x = 1"},
            {"path": "b.py", "operation": "create", "content": "y = 2"},
        ]}
    
    monkeypatch.setattr(OllamaClient, "generate_json", mock_generate_json)
    
    client = OllamaClient()
    generator = OllamaChangeGenerator(client)
    
    # Plan with 2 files - should use fast path
    plan = ChangePlan(
        summary="Create small app",
        changes=[
            PlannedChange(path="a.py", operation="create", reason="first"),
            PlannedChange(path="b.py", operation="create", reason="second"),
        ],
        validation_commands=[]
    )
    request = TaskRequest(prompt="create 2 files")
    
    changes = generator.generate(request, plan, {})
    
    # Should have called generate_json only once (fast path)
    assert call_count[0] == 1
    assert len(changes) == 2


def test_ollama_generator_resumable_generation(monkeypatch):
    """Test that generation can resume from previous progress."""
    from code_builder_v2.models import TaskRequest, ChangePlan, PlannedChange, GenerationProgress
    
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("LUMINA_USE_LOCAL_OLLAMA", "true")
    
    call_count = [0]
    
    def mock_generate_json(self, prompt, model=None, progress=None):
        call_count[0] += 1
        file_idx = call_count[0] - 1
        return {"changes": [{
            "path": f"file{file_idx}.py",
            "operation": "create",
            "content": f"# File {file_idx}\nvalue = {file_idx}\n"
        }]}
    
    monkeypatch.setattr(OllamaClient, "generate_json", mock_generate_json)
    
    client = OllamaClient()
    generator = OllamaChangeGenerator(client)
    
    plan = ChangePlan(
        summary="Create multi-file app",
        changes=[
            PlannedChange(path="file0.py", operation="create", reason="first"),
            PlannedChange(path="file1.py", operation="create", reason="second"),
            PlannedChange(path="file2.py", operation="create", reason="third"),
        ],
        validation_commands=[]
    )
    request = TaskRequest(prompt="create 3 files")
    
    # First call: generate first 2 files (batch_size=2 would make 2 calls, but batch_size=1 makes 3)
    progress = GenerationProgress(
        total_files=3,
        batch_size=1,
        current_file_index=0,
        completed_files={}
    )
    changes = generator.generate(request, plan, {}, progress)
    
    # With batch_size=1, should make 3 calls for 3 files
    assert call_count[0] == 3
    assert len(changes) == 3
    assert changes[0].path == "file0.py"
    assert changes[1].path == "file1.py"
    assert changes[2].path == "file2.py"
    assert progress.current_file_index == 3
    assert progress.is_complete()
    
    # Second call with completed progress - should not call generate_json again
    call_count[0] = 0
    progress2 = GenerationProgress(
        total_files=3,
        batch_size=1,
        current_file_index=3,  # Already complete
        completed_files={
            "file0.py": {"path": "file0.py", "operation": "create", "content": "# File 0\nvalue = 0\n"},
            "file1.py": {"path": "file1.py", "operation": "create", "content": "# File 1\nvalue = 1\n"},
            "file2.py": {"path": "file2.py", "operation": "create", "content": "# File 2\nvalue = 2\n"},
        }
    )
    changes2 = generator.generate(request, plan, {}, progress2)
    
    # Should return existing completed files without calling generate_json
    assert call_count[0] == 0
    assert len(changes2) == 3
    assert changes2[0].path == "file0.py"
    assert changes2[1].path == "file1.py"
    assert changes2[2].path == "file2.py"


def test_ollama_generator_batch_generation(monkeypatch):
    """Test that batch generation works with configurable batch size."""
    from code_builder_v2.models import TaskRequest, ChangePlan, PlannedChange
    
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("LUMINA_USE_LOCAL_OLLAMA", "true")
    
    call_count = [0]
    batch_sizes = []
    
    def mock_generate_json(self, prompt, model=None, progress=None):
        call_count[0] += 1
        # Return multiple files per call based on what was requested
        batch_sizes.append(call_count[0])
        file_idx = call_count[0] - 1
        # Each batch returns 2 files
        changes = []
        for i in range(2):
            idx = file_idx * 2 + i
            if idx < 4:  # Total 4 files
                changes.append({
                    "path": f"file{idx}.py",
                    "operation": "create",
                    "content": f"# File {idx}\nvalue = {idx}\n"
                })
        return {"changes": changes}
    
    monkeypatch.setattr(OllamaClient, "generate_json", mock_generate_json)
    
    client = OllamaClient()
    generator = OllamaChangeGenerator(client)
    
    plan = ChangePlan(
        summary="Create multi-file app",
        changes=[
            PlannedChange(path="file0.py", operation="create", reason="first"),
            PlannedChange(path="file1.py", operation="create", reason="second"),
            PlannedChange(path="file2.py", operation="create", reason="third"),
            PlannedChange(path="file3.py", operation="create", reason="fourth"),
        ],
        validation_commands=[]
    )
    request = TaskRequest(prompt="create 4 files", batch_size=2)
    
    changes = generator.generate(request, plan, {})
    
    # Should have called generate_json 2 times (4 files / batch_size=2)
    assert call_count[0] == 2
    assert len(changes) == 4
    assert changes[0].path == "file0.py"
    assert changes[1].path == "file1.py"
    assert changes[2].path == "file2.py"
    assert changes[3].path == "file3.py"


def test_ollama_client_skips_rate_limited_provider(monkeypatch):
    """Test that client skips providers marked as rate-limited in progress."""
    from code_builder_v2.models import GenerationProgress
    
    monkeypatch.setenv("GROQ_API_KEY", "fake-key")
    monkeypatch.setenv("HF_TOKEN", "fake-token")
    monkeypatch.setenv("LUMINA_USE_LOCAL_OLLAMA", "true")
    
    call_order = []
    
    def mock_groq(self, prompt, model=None):
        call_order.append("groq")
        raise RateLimitError("Rate limit exceeded", provider="groq", model="test")
    
    def mock_hf(self, prompt, model=None):
        call_order.append("huggingface")
        return {"changes": [{"path": "a.py", "operation": "create", "content": "x = 1"}]}
    
    def mock_ollama(self, prompt, model=None):
        call_order.append("ollama")
        return {"changes": [{"path": "b.py", "operation": "create", "content": "y = 2"}]}
    
    monkeypatch.setattr(OllamaClient, "_generate_with_groq", mock_groq)
    monkeypatch.setattr(OllamaClient, "_generate_with_huggingface", mock_hf)
    monkeypatch.setattr(OllamaClient, "_generate_with_local_ollama", mock_ollama)
    
    client = OllamaClient()
    
    # First call without progress - should try groq, fail, then try hf
    result = client.generate_json("test prompt")
    assert result == {"changes": [{"path": "a.py", "operation": "create", "content": "x = 1"}]}
    assert "groq" in call_order
    assert "huggingface" in call_order
    
    # Now with progress that marks groq as rate-limited
    progress = GenerationProgress()
    progress.add_rate_limited_provider("groq")
    
    call_order.clear()
    result = client.generate_json("test prompt", progress=progress)
    assert result == {"changes": [{"path": "a.py", "operation": "create", "content": "x = 1"}]}
    # Should skip groq and go directly to huggingface
    assert "groq" not in call_order
    assert "huggingface" in call_order
