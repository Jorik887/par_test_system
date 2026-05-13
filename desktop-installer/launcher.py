from __future__ import annotations

import contextlib
import os
import socket
import subprocess
import sys
import threading
import time
import winreg
from pathlib import Path
from typing import Optional

import uvicorn
import webview


APP_TITLE = "Paragraph Test System"
HEALTH_PATH = "/health"
SERVER_HOST = "127.0.0.1"
SERVER_PORT = 8000
SERVER_START_TIMEOUT_SEC = 45


def _repo_root() -> Path:
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return Path(meipass)
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def _backend_dir(repo_root: Path) -> Path:
    return repo_root / "backend"


def _prepare_python_path(repo_root: Path) -> None:
    backend_root = _backend_dir(repo_root)
    if str(backend_root) not in sys.path:
        sys.path.insert(0, str(backend_root))


def _wait_for_server(host: str, port: int, timeout_sec: int) -> bool:
    deadline = time.time() + timeout_sec
    while time.time() < deadline:
        with contextlib.closing(socket.socket(socket.AF_INET, socket.SOCK_STREAM)) as sock:
            sock.settimeout(1.0)
            if sock.connect_ex((host, port)) == 0:
                return True
        time.sleep(0.25)
    return False


def _show_fatal_dialog(message: str) -> None:
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(0, message, APP_TITLE, 0x10)
    except Exception:
        print(message, file=sys.stderr)


def _write_runtime_log(message: str) -> None:
    try:
        base = Path(os.getenv("APPDATA", str(Path.home()))) / "ParagraphTestSystemDesktop"
        p = base / "desktop_runtime.log"
        stamp = time.strftime("%Y-%m-%d %H:%M:%S")
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(f"[{stamp}] {message}\n")
    except Exception:
        pass


def _appdata_root() -> Path:
    return Path(os.getenv("APPDATA", str(Path.home()))) / "ParagraphTestSystemDesktop"


def _ensure_workdir(repo_root: Path) -> None:
    backend_dir = _backend_dir(repo_root)
    if backend_dir.exists():
        os.chdir(str(backend_dir))


def _is_webview2_runtime_installed() -> bool:
    app_guid = r"{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
    registry_paths = (
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{app_guid}"),
        (winreg.HKEY_LOCAL_MACHINE, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{app_guid}"),
        (winreg.HKEY_CURRENT_USER, rf"SOFTWARE\Microsoft\EdgeUpdate\Clients\{app_guid}"),
    )
    for hive, path in registry_paths:
        try:
            key = winreg.OpenKey(hive, path)
            value, _ = winreg.QueryValueEx(key, "pv")
            if str(value or "").strip() and str(value).strip() != "0.0.0.0":
                return True
        except OSError:
            continue
    return False


def _ensure_webview2_runtime(repo_root: Path) -> None:
    if _is_webview2_runtime_installed():
        _write_runtime_log("WebView2 runtime detected")
        return

    candidates = [
        repo_root / "WebView2RuntimeInstallerX64.exe",
        repo_root / "WebView2RuntimeInstallerX86.exe",
        _repo_root() / "WebView2RuntimeInstallerX64.exe",
        _repo_root() / "WebView2RuntimeInstallerX86.exe",
    ]
    installer = next((p for p in candidates if p.exists()), None)
    if installer is None:
        _write_runtime_log("WebView2 runtime missing and installer not found in app payload")
        return

    _write_runtime_log(f"WebView2 runtime missing, running installer: {installer}")
    try:
        result = subprocess.run(
            [str(installer), "/silent", "/install"],
            check=False,
            timeout=240,
            creationflags=0x08000000,  # CREATE_NO_WINDOW
        )
        _write_runtime_log(f"WebView2 installer exit code: {result.returncode}")
    except Exception as exc:
        _write_runtime_log(f"WebView2 installer execution error: {exc}")

    # Give updater a short time to finalize registry entries.
    time.sleep(4.0)
    if not _is_webview2_runtime_installed():
        _write_runtime_log("WebView2 runtime still missing after auto-install attempt")
        return
    _write_runtime_log("WebView2 runtime installed successfully")


def _ensure_backend_env(repo_root: Path) -> None:
    backend_dir = _backend_dir(repo_root)
    env_path = backend_dir / ".env"
    if env_path.exists():
        return
    # Desktop setup must run without shipping project .env to testers.
    # Keep compatibility: if file exists it is used; otherwise env vars below are applied.
    return


def _ensure_desktop_defaults() -> None:
    app_root = _appdata_root()
    app_root.mkdir(parents=True, exist_ok=True)
    backend_db = app_root / "backend.sqlite3"

    defaults = {
        "APP_ENV": "prod",
        "BACKEND_DB_DSN": f"sqlite+aiosqlite:///{backend_db.as_posix()}",
        "PARAGRAPH_REST_BASE_URL": "http://127.0.0.1:5000",
        "ISHD_HOST": "127.0.0.1",
        "ISHD_PORT": "50200",
        "ISHD_HOST_ID": "par_test_system",
        "ISHD_SOFTWARE_NAME": "Paragraph Test System",
        "ISHD_TARGET_HOST_ID": "paragraf",
        "ISHD_TARGET_HOST_IDS": "paragraf",
        "ISHD_DEFAULT_PORT": "8080",
        "ISHD_REQUEST_TIMEOUT_SEC": "8.0",
        "ISHD_DOC_RESPONSE_TIMEOUT_SEC": "35.0",
        "ISHD_ACTION_DIRECT_TIMEOUT_SEC": "1.0",
        "ISHD_ACTION_RESULT_TIMEOUT_SEC": "35.0",
        # Optional defaults for standalone desktop
        "PARAGRAPH_DB_DSN": "",
        "PARAGRAPH_FILE_DIRS": str((app_root / "paragraph_files").resolve()),
        "CRYPTO_KEY": "",
    }

    for key, value in defaults.items():
        if not str(os.getenv(key, "")).strip():
            os.environ[key] = value


async def _ensure_backend_schema() -> None:
    # Minimal runtime init for fresh desktop installs (no pre-migrated DB).
    from src.core.db import engine  # type: ignore
    from src.models import Base  # type: ignore

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


class DesktopRuntime:
    def __init__(self, repo_root: Path) -> None:
        self.repo_root = repo_root
        self.server: Optional[uvicorn.Server] = None
        self.server_thread: Optional[threading.Thread] = None

    def start_backend(self) -> None:
        _prepare_python_path(self.repo_root)
        _ensure_backend_env(self.repo_root)
        _ensure_desktop_defaults()
        _ensure_workdir(self.repo_root)
        reports_dir = _appdata_root() / "reports" / "autotest"
        reports_dir.mkdir(parents=True, exist_ok=True)
        os.environ["PARAGRAPH_TEST_REPORTS_DIR"] = str(reports_dir)
        _write_runtime_log(f"Desktop startup: reports_dir={reports_dir}")

        try:
            from src.main import app  # type: ignore
            import asyncio

            asyncio.run(_ensure_backend_schema())
        except Exception as exc:
            raise RuntimeError(
                "Не удалось импортировать backend приложение. "
                "Проверьте целостность установки и права доступа к каталогу %APPDATA%\\ParagraphTestSystemDesktop. "
                f"Детали: {exc}"
            ) from exc

        config = uvicorn.Config(
            app=app,
            host=SERVER_HOST,
            port=SERVER_PORT,
            log_level="info",
            access_log=False,
        )
        self.server = uvicorn.Server(config)
        self.server_thread = threading.Thread(target=self.server.run, name="backend-server", daemon=True)
        self.server_thread.start()
        _write_runtime_log(f"Backend thread started on {SERVER_HOST}:{SERVER_PORT}")

        if not _wait_for_server(SERVER_HOST, SERVER_PORT, SERVER_START_TIMEOUT_SEC):
            raise RuntimeError(
                "Backend не поднялся за отведенное время. "
                "Проверьте права доступа и runtime-лог в %APPDATA%\\ParagraphTestSystemDesktop\\desktop_runtime.log."
            )
        _write_runtime_log("Backend health port is reachable")

    def stop_backend(self) -> None:
        if self.server is None:
            return
        self.server.should_exit = True
        _write_runtime_log("Backend shutdown requested")
        if self.server_thread is not None and self.server_thread.is_alive():
            self.server_thread.join(timeout=15)
            _write_runtime_log("Backend thread joined")


runtime: Optional[DesktopRuntime] = None


def _on_window_closed() -> None:
    global runtime
    if runtime is not None:
        runtime.stop_backend()


def main() -> int:
    global runtime
    repo_root = _repo_root()
    runtime = DesktopRuntime(repo_root)

    try:
        _ensure_webview2_runtime(repo_root)
        runtime.start_backend()
    except Exception as exc:
        _write_runtime_log(f"Startup error: {exc}")
        _show_fatal_dialog(str(exc))
        return 1

    ui_url = f"http://{SERVER_HOST}:{SERVER_PORT}/ui"
    _write_runtime_log(f"Opening UI: {ui_url}")
    webview.create_window(
        APP_TITLE,
        ui_url,
        width=1440,
        height=920,
        min_size=(1180, 760),
        resizable=True,
    )

    last_error: Optional[Exception] = None
    for gui_name in ("edgechromium", "cef", "mshtml"):
        try:
            _write_runtime_log(f"Trying UI engine: {gui_name}")
            webview.start(gui=gui_name, debug=False)
            last_error = None
            break
        except Exception as exc:
            last_error = exc
            _write_runtime_log(f"UI engine failed ({gui_name}): {exc}")

    if last_error is not None:
        _show_fatal_dialog(f"Не удалось запустить UI-движок: {last_error}")

    _on_window_closed()
    return 0 if last_error is None else 1


if __name__ == "__main__":
    raise SystemExit(main())
