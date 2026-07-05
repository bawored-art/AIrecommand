from pathlib import Path

import yaml
from dotenv import load_dotenv

DEFAULT_CONFIG_PATH = "config.yaml"


def load_config(path: str = DEFAULT_CONFIG_PATH) -> dict:
    """config.yaml을 읽고 .env를 환경변수에 로드한다."""
    load_dotenv(override=False)
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(f"설정 파일을 찾을 수 없습니다: {config_path}")
    with config_path.open("r", encoding="utf-8") as f:
        return yaml.safe_load(f)
