from pydantic_settings import BaseSettings, SettingsConfigDict

APP_VERSION = "0.1.0"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # OpenAI (STT + LLM + TTS)
    openai_api_key: str = ""
    openai_chat_model: str = "gpt-4o-mini"
    openai_stt_model: str = "gpt-4o-mini-transcribe"
    openai_tts_model: str = "gpt-4o-mini-tts"
    openai_tts_voice: str = "alloy"

    # Places provider: "foursquare" or "geoapify"
    places_provider: str = "foursquare"
    foursquare_api_key: str = ""
    geoapify_api_key: str = ""

    database_url: str = "sqlite:///./data/sarjy.db"
    app_env: str = "dev"
    log_level: str = "INFO"
    rate_limit_enabled: bool = True


settings = Settings()
