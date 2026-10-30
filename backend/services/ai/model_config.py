from dataclasses import dataclass


@dataclass(frozen=True)
class ModelConfig:
    provider: str
    model: str
    temperature: float = 0.1
    max_tokens: int = 1024
    timeout_seconds: float = 120.0
    api_key_env: str | None = None
    base_url: str | None = None
    allow_cloud_document_content: bool = False
    input_cost_per_million: float | None = None
    output_cost_per_million: float | None = None

    def __post_init__(self) -> None:
        if self.provider not in {"ollama", "openai", "gemini", "anthropic", "groq", "openrouter"}:
            raise ValueError("unsupported provider")
        if not self.model.strip() or not 0 <= self.temperature <= 2:
            raise ValueError("invalid model configuration")
        if self.max_tokens <= 0 or self.timeout_seconds <= 0:
            raise ValueError("invalid model configuration")
        if self.provider != "ollama" and not self.api_key_env:
            raise ValueError("cloud provider requires an API key environment variable")

    @property
    def is_cloud(self) -> bool:
        return self.provider != "ollama"
