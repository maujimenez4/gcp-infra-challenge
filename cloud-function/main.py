import functions_framework
import logging
import json
from datetime import datetime, timezone
from google.cloud import logging as cloud_logging

try:
    log_client = cloud_logging.Client()
    log_client.setup_logging()
except Exception:
    pass

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

ALLOWED_CONTENT_TYPES = {
    "text/plain", "application/json", "text/csv",
    "application/pdf", "image/jpeg", "image/png",
}
MAX_FILE_SIZE_BYTES = 500 * 1024 * 1024  # 500 MB

@functions_framework.cloud_event
def process_gcs_upload(cloud_event):
    try:
        data = cloud_event.data
        _validate_event_data(data)
    except (KeyError, TypeError, ValueError) as exc:
        logger.error(json.dumps({
            "severity": "ERROR",
            "event": "invalid_event_payload",
            "error": str(exc),
            "timestamp": _now_iso(),
        }))
        raise

    metadata = _extract_metadata(data)
    warnings = _run_validations(metadata)
    _log_success(metadata, warnings)

def _validate_event_data(data):
    required = ["bucket", "name", "size", "contentType", "timeCreated"]
    missing = [f for f in required if f not in data]
    if missing:
        raise ValueError(f"Campos faltantes: {missing}")

def _extract_metadata(data):
    return {
        "bucket": data["bucket"],
        "name": data["name"],
        "size_bytes": int(data.get("size", 0)),
        "content_type": data.get("contentType", "application/octet-stream"),
        "time_created": data.get("timeCreated", ""),
        "generation": data.get("generation", ""),
        "processed_at": _now_iso(),
    }

def _run_validations(metadata):
    warnings = []
    if metadata["size_bytes"] > MAX_FILE_SIZE_BYTES:
        warnings.append(f"Archivo supera límite: {metadata['size_bytes']} bytes")
    if metadata["content_type"] not in ALLOWED_CONTENT_TYPES:
        warnings.append(f"Tipo no permitido: {metadata['content_type']}")
    return warnings

def _log_success(metadata, warnings):
    logger.info(json.dumps({
        "severity": "WARNING" if warnings else "INFO",
        "event": "file_uploaded",
        "metadata": metadata,
        "warnings": warnings,
        "timestamp": _now_iso(),
    }))

def _now_iso():
    return datetime.now(timezone.utc).isoformat()
