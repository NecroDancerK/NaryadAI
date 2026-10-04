from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://naryad:naryad_dev@localhost:5432/naryad"
    jwt_secret: str = "replace-in-non-demo-environments"
    access_token_minutes: int = 720
    llm_enabled: bool = False
    llm_base_url: str = "http://host.docker.internal:8080"
    llm_model: str = "Qwen3-4B-Q4_K_M"
    llm_timeout_seconds: float = 25.0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
