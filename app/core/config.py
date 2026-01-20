from functools import lru_cache

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    sqlalchemy_database_url: str = "sqlite:///./dev.db"
    google_client_id: str = ""
    google_client_secret: str = ""
    postgres_user: str = ""
    postgres_password: str = ""
    postgres_db: str = ""
    jwt_secret_key: str = "change-me"
    jwt_algorithm: str = "HS256"
    access_token_expire_minutes: int = 60 * 24
    gemini_api_key: str = "" 

    class Config:
        env_file = ".env"
        case_sensitive = False


@lru_cache
def get_settings() -> Settings:
    return Settings()
