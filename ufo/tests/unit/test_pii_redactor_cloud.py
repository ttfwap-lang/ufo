from ufo.security.pii_redactor import PIIRedactor
from ufo.llm.endpoint import is_local_endpoint, is_cloud_agent_config, is_local_agent_config


def test_pii_redactor_text_scrubbing():
    """Verify PIIRedactor scrubs financial numbers, credit cards, SSNs, and emails."""
    redactor = PIIRedactor()

    text = "User John Doe (SSN: 123-45-6789) transfer $1,450.00 from Account #12345678 to user@bank.com with card 4111-1111-1111-1111."
    redacted = redactor.redact_string(text)

    assert "123-45-6789" not in redacted
    assert "$1,450.00" not in redacted
    assert "12345678" not in redacted
    assert "4111-1111-1111-1111" not in redacted
    assert "[REDACTED]" in redacted


def test_pii_redactor_should_redact_for_model():
    """Verify PIIRedactor only activates for cloud models when REDACT_FOR_CLOUD_ONLY is true."""
    redactor = PIIRedactor()
    assert redactor.should_redact_for_model(is_cloud=True) is True
    assert redactor.should_redact_for_model(is_cloud=False) is False


def test_qwen_deepseek_endpoint_classification():
    """Verify public Qwen DashScope and DeepSeek endpoints are cloud, while localhost proxies are local."""
    # Public DashScope endpoint is cloud
    dashscope_cfg = {
        "API_TYPE": "qwen",
        "API_BASE": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "API_KEY": "sk-dashscope-secret",
    }
    assert is_local_agent_config(dashscope_cfg) is False
    assert is_cloud_agent_config(dashscope_cfg) is True

    # Public DeepSeek endpoint is cloud
    deepseek_cfg = {
        "API_TYPE": "deepseek",
        "API_BASE": "https://api.deepseek.com/v1",
        "API_KEY": "sk-deepseek-secret",
    }
    assert is_local_agent_config(deepseek_cfg) is False
    assert is_cloud_agent_config(deepseek_cfg) is True

    # Localhost LiteLLM proxy with Qwen model is local
    local_proxy_cfg = {
        "API_TYPE": "openai",
        "API_BASE": "http://localhost:4000/v1",
        "API_KEY": "sk-local",
    }
    assert is_local_agent_config(local_proxy_cfg) is True
    assert is_cloud_agent_config(local_proxy_cfg) is False
