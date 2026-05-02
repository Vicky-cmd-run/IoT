from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_env: str = "development"
    backend_host: str = "0.0.0.0"
    backend_port: int = 8000
    traci_enabled: bool = False
    sumo_binary: str = "sumo"
    sumo_config: str = "../simulation/config.sumocfg"
    map_provider: str = "osm"
    openweather_api_key: str = ""
    tomtom_api_key: str = ""
    database_url: str = "postgresql://postgres:change_me@db:5432/smart_traffic"
    jwt_secret: str = ""
    jwt_algorithm: str = "HS256"
    admin_email: str = "vigneshgnanasekaran8@gmail.com"
    admin_password: str = "Viggu@2005"

    model_config = SettingsConfigDict(
        env_file="../.env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


settings = Settings()
