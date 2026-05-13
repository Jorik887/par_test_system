import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional


def _resolve_reports_dir() -> Path:
    # Dlya sebya: desktop-upakovka mozhet byt' v Program Files, tam net prav zapisi.
    # Pozvolyaem zadat' katalog cherez env, inache sokhranyaem staroe povedenie.
    env_dir = str(os.getenv("PARAGRAPH_TEST_REPORTS_DIR", "")).strip()
    if env_dir:
        return Path(env_dir).expanduser().resolve()
    return Path(__file__).resolve().parents[2] / "reports" / "autotest"


_REPORTS_DIR = _resolve_reports_dir()
_REPORTS_DIR.mkdir(parents=True, exist_ok=True)
_ARTIFACTS_ROOT = _REPORTS_DIR / "_artifacts"
_ARTIFACTS_ROOT.mkdir(parents=True, exist_ok=True)
_INDEX_PATH = _REPORTS_DIR / "_index.json"
_INDEX_LOCK = threading.RLock()


def _safe_token(value: str, *, default: str) -> str:
    safe = "".join(ch for ch in str(value or "") if ch.isalnum() or ch in ("-", "_", "."))
    return safe or default


def _report_path(run_id: str) -> Path:
    safe = _safe_token(run_id, default="run")
    return _REPORTS_DIR / f"{safe}.json"


def _artifact_dir(run_id: str) -> Path:
    safe = _safe_token(run_id, default="run")
    return _ARTIFACTS_ROOT / safe


def _artifact_path(run_id: str, artifact_id: str, filename: str) -> Path:
    aid = _safe_token(artifact_id, default="artifact")
    fname = _safe_token(filename, default="artifact.bin")
    return _artifact_dir(run_id) / f"{aid}__{fname}"


def _compact_report_meta(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "run_id": payload.get("run_id"),
        "started_at": payload.get("started_at"),
        "finished_at": payload.get("finished_at"),
        "status": payload.get("status"),
        "source_dict_name": payload.get("source_dict_name"),
        "target_id": payload.get("target_id"),
        "target_name": payload.get("target_name"),
        "summary": payload.get("summary", {}),
    }


def _read_index() -> List[Dict[str, Any]]:
    if not _INDEX_PATH.exists():
        return []
    try:
        payload = json.loads(_INDEX_PATH.read_text(encoding="utf-8"))
    except Exception:
        return []
    if not isinstance(payload, list):
        return []
    out: List[Dict[str, Any]] = []
    for item in payload:
        if isinstance(item, dict) and item.get("run_id"):
            out.append(_compact_report_meta(item))
    return out


def _write_index(items: List[Dict[str, Any]]) -> None:
    _INDEX_PATH.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")


def _rebuild_index() -> List[Dict[str, Any]]:
    files = sorted(
        _REPORTS_DIR.glob("*.json"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )
    items: List[Dict[str, Any]] = []
    for path in files:
        if path.name == _INDEX_PATH.name:
            continue
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        if not isinstance(payload, dict):
            continue
        items.append(_compact_report_meta(payload))
    return items


def save_report(report: Dict[str, Any]) -> Path:
    # Dlya sebya: hranim itog avtoprogona v json, chtoby nachalnik mog ego skachat i prosmotret.
    run_id = str(report.get("run_id", "")).strip()
    if not run_id:
        raise ValueError("run_id is required for report saving")

    path = _report_path(run_id)
    payload_text = json.dumps(report, ensure_ascii=False, indent=2)
    path.write_text(payload_text, encoding="utf-8")

    meta = _compact_report_meta(report)
    with _INDEX_LOCK:
        index = _read_index()
        index = [item for item in index if str(item.get("run_id")) != run_id]
        index.insert(0, meta)
        _write_index(index[:1000])

    return path


def load_report(run_id: str) -> Optional[Dict[str, Any]]:
    # Dlya sebya: zagruzhaem odin otchet po id.
    path = _report_path(run_id)
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def update_report(run_id: str, mutator) -> Optional[Dict[str, Any]]:
    # Dlya sebya: atomarno obnovit' payload otcheta i sohranit' indeks.
    path = _report_path(run_id)
    if not path.exists():
        return None
    with _INDEX_LOCK:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            payload = {"run_id": run_id}
        updated = mutator(payload)
        if not isinstance(updated, dict):
            updated = payload
        path.write_text(json.dumps(updated, ensure_ascii=False, indent=2), encoding="utf-8")
        meta = _compact_report_meta(updated)
        index = _read_index()
        index = [item for item in index if str(item.get("run_id")) != run_id]
        index.insert(0, meta)
        _write_index(index[:1000])
        return updated


def save_artifact(
    *,
    run_id: str,
    data: bytes,
    filename: str,
    content_type: str = "application/octet-stream",
    kind: str = "downloaded_file",
    step_code: Optional[str] = None,
) -> Dict[str, Any]:
    # Dlya sebya: sohranyaem fail-artefakt dlya skachivaniya iz UI po run_id.
    rid = str(run_id or "").strip()
    if not rid:
        raise ValueError("run_id is required")
    aid = f"art_{uuid.uuid4().hex[:12]}"
    safe_filename = _safe_token(filename, default="artifact.bin")
    path = _artifact_path(rid, aid, safe_filename)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    return {
        "id": aid,
        "kind": str(kind or "downloaded_file"),
        "filename": safe_filename,
        "size_bytes": int(len(data)),
        "content_type": str(content_type or "application/octet-stream"),
        "step_code": str(step_code or ""),
    }


def add_report_artifact(run_id: str, artifact_meta: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # Dlya sebya: dopisyvaem metadannye artefakta v JSON-otchet.
    rid = str(run_id or "").strip()
    if not rid:
        return None

    def mutate(payload: Dict[str, Any]) -> Dict[str, Any]:
        artifacts = payload.get("artifacts")
        if not isinstance(artifacts, list):
            artifacts = []
        aid = str(artifact_meta.get("id") or "")
        cleaned: List[Dict[str, Any]] = []
        for item in artifacts:
            if not isinstance(item, dict):
                continue
            if str(item.get("id") or "") == aid:
                continue
            cleaned.append(item)
        artifacts = cleaned
        artifacts.append(dict(artifact_meta))
        payload["artifacts"] = artifacts
        return payload

    return update_report(rid, mutate)


def get_artifact_path(run_id: str, artifact_id: str, filename: str) -> Optional[Path]:
    # Dlya sebya: poluchit' put' k konkretnomu failu artefakta.
    rid = str(run_id or "").strip()
    aid = str(artifact_id or "").strip()
    if not rid or not aid:
        return None
    path = _artifact_path(rid, aid, filename)
    if not path.exists():
        return None
    return path


def get_report_path(run_id: str) -> Optional[Path]:
    # Dlya sebya: nuzhno otdat' syroy json fail na skachivanie iz UI.
    path = _report_path(run_id)
    if not path.exists():
        return None
    return path


def delete_report(run_id: str) -> bool:
    # Dlya sebya: udalenie odnogo proogona iz istorii.
    run_id = str(run_id or "").strip()
    if not run_id:
        return False

    path = _report_path(run_id)
    removed = False
    if path.exists():
        path.unlink()
        removed = True
    adir = _artifact_dir(run_id)
    if adir.exists():
        for p in sorted(adir.rglob("*"), reverse=True):
            if p.is_file():
                p.unlink(missing_ok=True)
            elif p.is_dir():
                p.rmdir()
        if adir.exists():
            adir.rmdir()
        removed = True

    with _INDEX_LOCK:
        index = _read_index()
        new_index = [item for item in index if str(item.get("run_id")) != run_id]
        if len(new_index) != len(index):
            removed = True
            _write_index(new_index[:1000])

    return removed


def list_reports(*, limit: int = 20) -> List[Dict[str, Any]]:
    # Dlya sebya: dlya UI nuzhen bystryy spisok poslednih progonov.
    safe_limit = max(1, min(int(limit), 1000))
    with _INDEX_LOCK:
        index = _read_index()
        if not index:
            index = _rebuild_index()
            _write_index(index[:1000])
        return index[:safe_limit]
