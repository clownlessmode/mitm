from __future__ import annotations

from datetime import datetime


def _stamp() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _format_kv(kwargs: dict[str, object]) -> str:
    if not kwargs:
        return ""
    return " | " + " ".join(f"{key}={value!r}" for key, value in kwargs.items())


def info(scope: str, message: str, **kwargs: object) -> None:
    print(f"[{_stamp()}] [INFO] [{scope}] {message}{_format_kv(kwargs)}")


def warning(scope: str, message: str, **kwargs: object) -> None:
    print(f"[{_stamp()}] [WARN] [{scope}] {message}{_format_kv(kwargs)}")


def error(scope: str, message: str, **kwargs: object) -> None:
    print(f"[{_stamp()}] [ERR ] [{scope}] {message}{_format_kv(kwargs)}")

