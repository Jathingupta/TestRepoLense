from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    groq_api_key: str = ""
    groq_model: str = "openai/gpt-oss-20b"
    groq_base_url: str = "https://api.groq.com/openai/v1"
    max_files: int = 500
    max_file_bytes: int = 250000
    max_total_bytes: int = 12000000
    clone_timeout_seconds: int = 120
    cors_origins: str = "http://localhost:5173"
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")
    @property
    def allowed_origins(self):
        return [x.strip() for x in self.cors_origins.split(",") if x.strip()]
settings = Settings()
