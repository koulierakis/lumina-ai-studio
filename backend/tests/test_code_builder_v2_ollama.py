from code_builder_v2.models import TaskRequest
from code_builder_v2.ollama import OllamaChangeGenerator, OllamaClient, OllamaPlanner, OllamaError, JSONRecoveryError, _extract_json_object


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)

    def generate_json(self, prompt, model=None):
        return self.responses.pop(0)


class FakeClientWithRetry:
    """Fake client that fails first N times then succeeds."""
    def __init__(self, fail_responses, success_response):
        self.fail_responses = list(fail_responses)
        self.success_response = success_response
        self.call_count = 0

    def generate_json(self, prompt, model=None):
        self.call_count += 1
        if self.fail_responses:
            raise OllamaError(self.fail_responses.pop(0))
        return self.success_response


def test_ollama_planner_parses_structured_plan():
    client = FakeClient([{"summary":"x","changes":[{"path":"a.py","operation":"create","reason":"needed"}],"validation_commands":["pytest -q"]}])
    plan = OllamaPlanner(client).create_plan(TaskRequest(prompt="create a.py"))
    assert plan.changes[0].path == "a.py"


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
