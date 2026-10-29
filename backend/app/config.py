from pydantic_settings import BaseSettings, SettingsConfigDict
class Settings(BaseSettings):
    database_url: str = "sqlite:///./newscanvas.db"
    cors_origins: str = "http://localhost:5173"
    summarization_mode: str = "demo"
    summarization_model: str = "sshleifer/distilbart-cnn-12-6"
    image_provider: str = "demo"
    hf_inference_url: str = ""
    hf_api_token: str = ""
    pollinations_url: str = "https://image.pollinations.ai/prompt"
    pollinations_token: str = ""
    pollinations_model: str = "flux"
    image_fallback_to_demo: bool = True
    max_article_chars: int = 50000
    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=False)
settings = Settings()
