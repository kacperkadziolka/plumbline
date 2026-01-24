from pathlib import Path

from pydantic import computed_field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    PROJECT_NAME: str = "Plumbline"
    API_V1_STR: str = "/api/v1"

    DB_PATH: str = "./data/plumbline.db"

    @computed_field  # type: ignore[prop-decorator]
    @property
    def database_url(self) -> str:
        path = Path(self.DB_PATH)
        path.parent.mkdir(parents=True, exist_ok=True)
        return f"sqlite+aiosqlite:///{path}"


settings = Settings()  # pyright: ignore[reportCallIssue]
