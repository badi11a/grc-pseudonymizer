from pathlib import Path

import yaml


def load(config_path: str, db_url: str | None = None) -> dict:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    if db_url:
        cfg["db_url"] = db_url
    if "db_url" not in cfg:
        raise ValueError("db_url must be provided via config file or --db-url")
    if isinstance(cfg.get("hmac_key"), str):
        cfg["hmac_key"] = cfg["hmac_key"].encode()
    return cfg
