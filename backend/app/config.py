from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://naryad:naryad_dev@localhost:5432/naryad"
    jwt_secret: str = "replace-in-non-demo-environments"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

