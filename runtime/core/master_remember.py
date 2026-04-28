"""Encrypt the last master password on disk bound to local device key (convenience; not SSO-grade)."""

from __future__ import annotations


from cryptography.fernet import Fernet, InvalidToken

from runtime.core.security_util import restrict_secret_file

_DEVICE_KEY_NAME = "rem_device.key"
_REMEMBER_BLOB_NAME = "master_remember.fenc"


def _device_key_path(data_dir: Path) -> Path:
    return data_dir / _DEVICE_KEY_NAME


def _blob_path(data_dir: Path) -> Path:
    return data_dir / _REMEMBER_BLOB_NAME


def _fernet_for_data_dir(data_dir: Path) -> Fernet:
    data_dir.mkdir(parents=True, exist_ok=True)
    dk = _device_key_path(data_dir)
    if not dk.is_file():
        dk.write_bytes(Fernet.generate_key())
        restrict_secret_file(dk)
    key = dk.read_bytes()
    return Fernet(key)


def load_remembered_master(data_dir: Path) -> str | None:
    """Return decrypted master password if the blob exists."""
    bp = _blob_path(data_dir)
    if not bp.is_file():
        return None
    try:
        plain = _fernet_for_data_dir(Path(data_dir)).decrypt(bp.read_bytes())
        return plain.decode("utf-8").strip() or None
    except InvalidToken:
        return None
    except OSError:
        return None


def save_remembered_master(data_dir: Path, master_password: str) -> None:
    """Overwrite encrypted master password reminder."""
    d = Path(data_dir)
    f = _fernet_for_data_dir(d)
    bp = _blob_path(d)
    token = f.encrypt(master_password.encode("utf-8"))
    bp.write_bytes(token)
    restrict_secret_file(bp)


def clear_remembered_master(data_dir: Path) -> None:
    bp = _blob_path(data_dir)
    if bp.is_file():
        bp.unlink(missing_ok=True)
