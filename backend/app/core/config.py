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

    # Vision engine (Phase 7). An uploaded still image is
    # analysed for people. This is not a live camera feed.
    #
    # `vision_enabled` lets a deployment serve the rest of the
    # API without loading a detector at all.
    vision_enabled: bool = True

    # Detection thresholds. A detection below the confidence
    # threshold is discarded, and overlapping boxes are merged
    # with non-maximum suppression at the IoU threshold.
    vision_confidence_threshold: float = 0.45
    vision_iou_threshold: float = 0.50

    # Uploads larger than this are rejected before the body is
    # read into memory in full.
    vision_max_upload_bytes: int = 10 * 1024 * 1024

    # Path to the YOLO weights file. Left empty the detector
    # looks for `yolo11n.pt` beside the vision package and
    # refuses to download anything.
    vision_model_path: str = ""

    # Browser origins allowed to call this API.
    #
    # A comma-separated list so a deployment can name the
    # origins it serves without a code change. The default is
    # the port `next dev` uses when 3000 is free.
    #
    # This is here rather than hardcoded because the frontend
    # port moves: `next dev` falls back to 3001 when something
    # already holds 3000, and an origin that is not listed here
    # produces a response with no Access-Control-Allow-Origin
    # header, which the browser reports as ERR_FAILED. That
    # reads as "the API is down" when the API answered 200.
    cors_allowed_origins: str = (
        "http://localhost:3000,http://127.0.0.1:3000"
    )

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def cors_origin_list(self) -> list[str]:
        """
        The configured origins as a list, ready for the CORS
        middleware.

        Split here rather than at the call site so the parsing and
        its edge cases are testable on their own.
        """

        return [
            origin.strip()
            for origin in self.cors_allowed_origins.split(",")
            if origin.strip()
        ]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
