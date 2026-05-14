import json
import uuid
from datetime import datetime, timezone


def new_trace() -> dict:
    return {
        "run_id": str(uuid.uuid4()),
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": "0.1.0",
        "modulos": {},
        "normativa": ["RGPD Art. 32", "EDPB 01/2025", "ISO 27001:2022 A.8.33"],
    }


def save(trace: dict, path: str = "informe_trazabilidad.json") -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(trace, f, indent=2, ensure_ascii=False)
