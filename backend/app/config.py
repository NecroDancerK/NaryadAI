from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, SecretStr
from pydantic import field_validator
from urllib.parse import urlparse
from ipaddress import ip_address


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://naryad:naryad_dev@localhost:5432/naryad"
    jwt_secret: str = "replace-in-non-demo-environments"
    access_token_minutes: int = 720
    llm_enabled: bool = False
    llm_base_url: str = "http://host.docker.internal:8080"
    llm_model: str = "Qwen3-4B-Q4_K_M"
    llm_timeout_seconds: float = 25.0
    vlm_enabled: bool = False
    vlm_base_url: str = "http://host.docker.internal:8081"
    vlm_model: str = "NaryadAI-Qwen3-VL-4B"
    vlm_timeout_seconds: float = Field(default=90.0, gt=0, le=300)
    vlm_api_key: SecretStr | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    @field_validator("vlm_base_url")
    @classmethod
    def local_vlm_only(cls, value: str) -> str:
        url = urlparse(value)
        allowed = url.hostname in {"localhost", "host.docker.internal", "::1"}
        if not allowed:
            try:
                address = ip_address(url.hostname or "")
                allowed = address.is_loopback or (address.is_private and not address.is_unspecified and not address.is_link_local)
            except ValueError:
                pass
        if url.scheme not in {"http", "https"} or not allowed or url.username or url.password:
            raise ValueError("VLM_BASE_URL must point to a local/private server")
        return value


settings = Settings()
