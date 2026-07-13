import os
import re
from pathlib import Path

import yaml

_ENV_VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def _resolve_env_vars(value):
    """Recursively substitute ${VAR_NAME} placeholders with os.environ values.

    Lets keys such as fpe.key or hmac_key be kept out of the YAML file and
    injected at runtime instead (e.g. from a secrets manager or CI/CD).
    """
    if isinstance(value, str):
        def _sub(match: re.Match) -> str:
            var_name = match.group(1)
            if var_name not in os.environ:
                raise ValueError(
                    f"Environment variable '{var_name}' referenced in config "
                    f"(as ${{{var_name}}}) is not set"
                )
            return os.environ[var_name]
        return _ENV_VAR_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: _resolve_env_vars(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_resolve_env_vars(v) for v in value]
    return value


def load(config_path: str, db_url: str | None = None) -> dict:
    path = Path(config_path)
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")
    with path.open(encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    cfg = _resolve_env_vars(cfg)
    if db_url:
        cfg["db_url"] = db_url
    if "db_url" not in cfg:
        raise ValueError("db_url must be provided via config file or --db-url")
    if isinstance(cfg.get("hmac_key"), str):
        cfg["hmac_key"] = cfg["hmac_key"].encode()
    return cfg
