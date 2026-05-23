from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    edgar_user_agent: str
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    postgres_user: str = "sec_filings"
    postgres_password: str = "sec_filings_dev"
    postgres_db: str = "sec_filings"
    ollama_host: str = "http://localhost:11434"
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_user: str = ""
    smtp_password: str = ""
    digest_recipients: str = ""

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}

    @property
    def database_url(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )

    @property
    def database_url_sync(self) -> str:
        return (
            f"postgresql+psycopg://{self.postgres_user}:{self.postgres_password}"
            f"@{self.postgres_host}:{self.postgres_port}/{self.postgres_db}"
        )


class UserAgentNotConfiguredError(Exception):
    pass


def get_settings() -> Settings:
    try:
        settings = Settings()  # type: ignore[call-arg]
    except Exception as e:
        raise UserAgentNotConfiguredError(
            "EDGAR_USER_AGENT environment variable is required. "
            'Format: "AppName YourName your@email.com"'
        ) from e
    if not settings.edgar_user_agent.strip():
        raise UserAgentNotConfiguredError(
            "EDGAR_USER_AGENT must not be empty. "
            'Format: "AppName YourName your@email.com"'
        )
    return settings
