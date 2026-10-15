from functools import lru_cache

from pydantic_settings import (
    BaseSettings,
    SettingsConfigDict,
)


class Settings(BaseSettings):
    app_name: str = "Smart Campus Digital Twin API"
    app_version: str = "0.1.0"

    supabase_url: str
    supabase_service_role_key: str

    # Telemetry engine (Phase 5). Disabled by default so the
    # API starts unchanged. MQTT_HOST and MQTT_PORT default to
    # the broker started by `docker compose up -d`.
    mqtt_enabled: bool = False
    mqtt_host: str = "localhost"
    mqtt_port: int = 1883
    mqtt_topic_prefix: str = "smart-campus"

    # How often the simulator produces a reading per sensor,
    # and how often buffered readings are flushed to
    # Supabase.
    telemetry_tick_seconds: int = 5
    telemetry_flush_seconds: int = 10

    # Campus used by the intelligence endpoints when the caller
    # does not name one.
    default_campus_code: str = "CIT-MAIN"

    # The intelligence engine runs after telemetry is persisted.
    # It is off by default so the API starts unchanged.
    intelligence_enabled: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
