from pathlib import Path
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    BASE_DIR: Path = Path(__file__).resolve().parents[2]

    POPULATION_CSV: str = "data/processed/almaty_population_all.csv"
    TRANSPORT_CSV: str = "data/processed/almaty_transport_yearly.csv"
    AIR_YEARLY_CSV: str = "data/processed/air_yearly_from_monthlies.csv"
    AIR_YEARLY_EXTRA_CSV: str = "data/processed/almaty_yearly_from_excels.csv"

    DEFAULT_HORIZON: int = 80
    CHRONOS_MODEL: str = "amazon/chronos-t5-small"

    API_TITLE: str = "Almaty Air Quality Forecast API"
    API_VERSION: str = "1.0.0"

    class Config:
        env_file = ".env"


settings = Settings()
