import json
import socket
from http.client import HTTPException, RemoteDisconnected
from typing import Any, Dict, List, Optional, Tuple
from urllib import request, error, parse

from src.config.settings import settings


class ParagraphRestError(Exception):
    def __init__(self, message: str, status: Optional[int] = None, body: Optional[str] = None):
        # Dlya sebya: servisnyy helper (init).
        super().__init__(message)
        self.status = status
        self.body = body


def _build_url(path: str, *, base_url: Optional[str] = None) -> str:
    # Dlya sebya: servisnyy helper (build url).
    base = (base_url or settings.paragraph_rest_base_url).rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return base + path


def _request_json(
    method: str,
    path: str,
    *,
    base_url: Optional[str] = None,
    params: Optional[Dict[str, Any]] = None,
    payload: Optional[Dict[str, Any]] = None,
    timeout: int = 10,
) -> Any:
    # Dlya sebya: servisnyy helper (request json).
    url = _build_url(path, base_url=base_url)
    if params:
        url += "?" + parse.urlencode(params, doseq=True)

    data = None
    headers = {"Content-Type": "application/json"}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")

    req = request.Request(url, data=data, method=method, headers=headers)
    try:
        with request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            if not body:
                return None
            return json.loads(body)
    except error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        raise ParagraphRestError(f"REST {method} {path} failed", status=e.code, body=body)
    except (error.URLError, TimeoutError, socket.timeout, ConnectionResetError, HTTPException, RemoteDisconnected, OSError) as e:
        raise ParagraphRestError(f"REST {method} {path} failed: {e}")
    except json.JSONDecodeError as e:
        raise ParagraphRestError(f"REST {method} {path} returned non-JSON payload: {e}")


# Type mapping from API.pdf (Table 1).
TYPE_MAP = {
    "id": 0,
    "text": 1,
    "int": 2,
    "double": 3,
    "datetime": 4,
    "bool": 5,
    "relation": 6,
    "coord": 7,
    "marker": 8,
    "file": 9,
    "text_area": 10,
    "json": 11,
    "date": 12,
    "tle": 13,
}


def list_dicts(*, base_url: Optional[str] = None, timeout: int = 10) -> Any:
    # Dlya sebya: servisnaya operaciya "list dicts".
    return _request_json("GET", "/api/v1/meta/u_dict/", base_url=base_url, timeout=timeout)


def create_dict(
    name: str,
    *,
    base_url: Optional[str] = None,
    columns: Optional[List[Dict[str, Any]]] = None,
    visible: int = 0,
    dict_type: int = 0,
) -> Any:
    # Default single text column to keep creation minimal.
    # Dlya sebya: servisnaya operaciya "create dict".
    if not columns:
        columns = [
            {
                "name": "name",
                "type": TYPE_MAP["text"],
                "note": "text",
                "not_null": True,
                "mask": False,
                "interpretation": 3,
            }
        ]

    payload = {
        "data": {
            "name": name,
            "columns": columns,
            "visible": visible,
            "type": dict_type,
        }
    }
    return _request_json("POST", "/api/v1/meta/u_dict/", payload=payload, base_url=base_url)


def get_meta(table_uid: str, *, base_url: Optional[str] = None) -> Any:
    # Dlya sebya: servisnaya operaciya "get meta".
    return _request_json("GET", f"/api/v1/meta/u_dict/{table_uid}/", base_url=base_url)


def delete_dict(
    table_uid: str,
    *,
    delete_cascade: bool = False,
    base_url: Optional[str] = None,
) -> Any:
    # Dlya sebya: servisnaya operaciya "delete dict".
    params = {"delete_cascade": str(delete_cascade).lower()}
    return _request_json("DELETE", f"/api/v1/meta/u_dict/{table_uid}/", params=params, base_url=base_url)


def insert_rows(table_uid: str, rows: List[Dict[str, Any]], *, base_url: Optional[str] = None) -> Any:
    # Dlya sebya: servisnaya operaciya "insert rows".
    return _request_json("POST", f"/api/v1/u_dict/{table_uid}/rows", payload=rows, base_url=base_url)


def get_rows(
    table_uid: str,
    *,
    params: Optional[Dict[str, Any]] = None,
    base_url: Optional[str] = None,
) -> Any:
    # Dlya sebya: servisnaya operaciya "get rows".
    return _request_json("GET", f"/api/v1/u_dict/{table_uid}", params=params, base_url=base_url)


def update_row(
    table_uid: str,
    row_id: str,
    values: Dict[str, Any],
    *,
    base_url: Optional[str] = None,
) -> Any:
    # Dlya sebya: servisnaya operaciya "update row".
    return _request_json("PUT", f"/api/v1/u_dict/{table_uid}/rows/{row_id}", payload=values, base_url=base_url)
