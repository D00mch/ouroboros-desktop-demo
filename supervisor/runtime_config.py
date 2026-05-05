from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

@dataclass(frozen=True)
class RuntimeConfig:
    repo_dir: Path
    drive_root: Path
    launcher_path: Path
    github_user: str
    github_repo: str
    dialogs_endpoint: str = ""
    dialogs_bot_token: str = ""
    dialogs_app_id: int = 0
    dialogs_app_title: str = "Ouroboros"
    dialogs_device_title: str = "Ouroboros"
    dialogs_trust_all_server_certificates: bool = False
    dialogs_grpc_keepalive_time_ms: int = 30000
    dialogs_grpc_keepalive_timeout_ms: int = 10000
    dialogs_grpc_keepalive_permit_without_calls: bool = True


def _parse_bool_env(env: Mapping[str, str], key: str, default: bool = False) -> bool:
    value = env.get(key)
    if value is None or str(value).strip() == "":
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    raise ValueError(f"Invalid boolean value for {key}: {value}")


def _parse_int_env(env: Mapping[str, str], key: str, default: int) -> int:
    value = env.get(key)
    if value is None or str(value).strip() == "":
        return default
    return int(str(value).strip())


def load_runtime_config(env: Mapping[str, str], cwd: Path) -> RuntimeConfig:
    drive_root = Path(
        env.get("OUROBOROS_DATA_DIR")
        or env.get("OUROBOROS_DRIVE_ROOT")
        or (cwd / ".ouroboros_runtime")
    )
    return RuntimeConfig(
        repo_dir=Path(env.get("OUROBOROS_REPO_DIR") or cwd),
        drive_root=drive_root,
        launcher_path=Path(env.get("OUROBOROS_LAUNCHER_PATH") or (cwd / "launcher.py")),
        github_user=env.get("GITHUB_USER", ""),
        github_repo=env.get("GITHUB_REPO", ""),
        dialogs_endpoint=env.get("DIALOGS_GRPC_ENDPOINT", "https://ep.sberchat.sberbank.ru:443"),
        dialogs_bot_token=env.get("DIALOGS_BOT_TOKEN", ""),
        dialogs_app_id=int(env.get("DIALOGS_APP_ID", "0")),
        dialogs_app_title=env.get("DIALOGS_APP_TITLE", "Ouroboros"),
        dialogs_device_title=env.get("DIALOGS_DEVICE_TITLE", "Ouroboros"),
        dialogs_trust_all_server_certificates=_parse_bool_env(
            env,
            "DIALOGS_GRPC_TRUST_ALL_SERVER_CERTIFICATES",
            default=True,
        ),
        dialogs_grpc_keepalive_time_ms=_parse_int_env(
            env,
            "DIALOGS_GRPC_KEEPALIVE_TIME_MS",
            default=30000,
        ),
        dialogs_grpc_keepalive_timeout_ms=_parse_int_env(
            env,
            "DIALOGS_GRPC_KEEPALIVE_TIMEOUT_MS",
            default=10000,
        ),
        dialogs_grpc_keepalive_permit_without_calls=_parse_bool_env(
            env,
            "DIALOGS_GRPC_KEEPALIVE_PERMIT_WITHOUT_CALLS",
            default=True,
        ),
    )
