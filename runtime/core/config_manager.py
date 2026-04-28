"""Encrypted Binance credential store: multiple pairs + public manifest."""

from __future__ import annotations

import base64
import json
import os
import uuid
from pathlib import Path
from typing import Any, List, Optional, Tuple

from cryptography.fernet import Fernet, InvalidToken
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

from runtime.core.security_util import restrict_secret_file

_DEFAULT_ITERATIONS = 480_000
_MIN_MASTER_PASSWORD_LEN = 12

_MANIFEST = "credential_public.json"
_ACTIVE = "active_credential_id.txt"


class ConfigManager:
    """Persist one or more API key + secret lists under a single master password."""

    def __init__(self, data_dir: Path) -> None:
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._cred_path = self.data_dir / "credentials.enc"
        self._salt_path = self.data_dir / "salt.bin"
        self._manifest_path = self.data_dir / _MANIFEST
        self._active_path = self.data_dir / _ACTIVE

    def exists(self) -> bool:
        return self._cred_path.is_file()

    @staticmethod
    def _derive_key(password: str, salt: bytes) -> bytes:
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,
            salt=salt,
            iterations=_DEFAULT_ITERATIONS,
        )
        raw = kdf.derive(password.encode("utf-8"))
        return base64.urlsafe_b64encode(raw)

    def _load_or_create_salt(self) -> bytes:
        if self._salt_path.is_file():
            return self._salt_path.read_bytes()
        salt = os.urandom(16)
        self._salt_path.write_bytes(salt)
        restrict_secret_file(self._salt_path)
        return salt

    @staticmethod
    def validate_master_password_strength(master_password: str) -> None:
        if len(master_password) < _MIN_MASTER_PASSWORD_LEN:
            raise ValueError(
                f"Master password must be at least {_MIN_MASTER_PASSWORD_LEN} characters"
            )

    def _fernet(self, master_password: str) -> Fernet:
        salt = self._load_or_create_salt()
        key = self._derive_key(master_password, salt)
        return Fernet(key)

    def _decrypt_payload(self, master_password: str) -> Optional[dict[str, Any]]:
        if not self.exists() or not self._salt_path.is_file():
            return None
        f = self._fernet(master_password)
        try:
            raw = f.decrypt(self._cred_path.read_bytes())
        except InvalidToken:
            return None
        data = json.loads(raw.decode("utf-8"))
        migrated = self._migrate_payload_if_needed(data)
        if migrated != data:
            self._encrypt_and_write(migrated, master_password)
        return migrated

    def _migrate_payload_if_needed(self, data: Any) -> dict[str, Any]:
        if not isinstance(data, dict):
            return {"v": 2, "items": []}
        if data.get("v") == 2 and isinstance(data.get("items"), list):
            return data
        if "api_key" in data and "api_secret" in data:
            cid = str(uuid.uuid4())
            return {
                "v": 2,
                "items": [
                    {
                        "id": cid,
                        "api_key": str(data["api_key"]).strip(),
                        "api_secret": str(data["api_secret"]).strip(),
                    }
                ],
            }
        return {"v": 2, "items": []}

    def _encrypt_and_write(self, payload: dict[str, Any], master_password: str) -> None:
        self.validate_master_password_strength(master_password)
        salt = self._load_or_create_salt()
        key = self._derive_key(master_password, salt)
        f = Fernet(key)
        blob = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        token = f.encrypt(blob.encode("utf-8"))
        self._cred_path.write_bytes(token)
        restrict_secret_file(self._cred_path)
        self._write_manifest_from_payload(payload)

    def _write_manifest_from_payload(self, payload: dict[str, Any]) -> None:
        items = payload.get("items") if isinstance(payload.get("items"), list) else []
        rows: List[dict[str, str]] = []
        for it in items:
            if not isinstance(it, dict):
                continue
            cid = str(it.get("id", "")).strip()
            ak = str(it.get("api_key", "")).strip()
            if cid and ak:
                rows.append({"id": cid, "public_key": ak})
        tmp = self._manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, indent=0), encoding="utf-8")
        tmp.replace(self._manifest_path)
        restrict_secret_file(self._manifest_path)

    def list_public_credentials(self) -> List[dict[str, str]]:
        """Ids and public API keys only (no secrets)."""
        if not self._manifest_path.is_file():
            return []
        try:
            raw = json.loads(self._manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return []
        if not isinstance(raw, list):
            return []
        out: List[dict[str, str]] = []
        for row in raw:
            if isinstance(row, dict) and row.get("id") and row.get("public_key"):
                out.append({"id": str(row["id"]), "public_key": str(row["public_key"])})
        return out

    def get_active_credential_id(self) -> Optional[str]:
        if not self._active_path.is_file():
            return None
        try:
            s = self._active_path.read_text(encoding="utf-8").strip()
            return s or None
        except OSError:
            return None

    def set_active_credential_id(self, credential_id: Optional[str]) -> None:
        if not credential_id:
            if self._active_path.is_file():
                self._active_path.unlink()
            return
        self._active_path.write_text(credential_id.strip(), encoding="utf-8")
        restrict_secret_file(self._active_path)

    def _find_item(
        self, items: List[dict[str, Any]], credential_id: str
    ) -> Optional[dict[str, Any]]:
        for it in items:
            if isinstance(it, dict) and str(it.get("id")) == credential_id:
                return it
        return None

    def add_credential(self, api_key: str, api_secret: str, master_password: str) -> str:
        self.validate_master_password_strength(master_password)
        payload = self._decrypt_payload(master_password)
        if payload is None:
            payload = {"v": 2, "items": []}
        items = payload.get("items")
        if not isinstance(items, list):
            items = []
        cid = str(uuid.uuid4())
        items.append(
            {
                "id": cid,
                "api_key": api_key.strip(),
                "api_secret": api_secret.strip(),
            }
        )
        payload["v"] = 2
        payload["items"] = items
        self._encrypt_and_write(payload, master_password)
        return cid

    def remove_credential(self, credential_id: str, master_password: str) -> bool:
        payload = self._decrypt_payload(master_password)
        if payload is None:
            return False
        items = payload.get("items")
        if not isinstance(items, list):
            return False
        new_items = [it for it in items if isinstance(it, dict) and str(it.get("id")) != credential_id]
        if len(new_items) == len(items):
            return False
        payload["items"] = new_items
        self._encrypt_and_write(payload, master_password)
        if self.get_active_credential_id() == credential_id:
            self.set_active_credential_id(new_items[0]["id"] if new_items else None)
        return True

    def get_secret_pair(self, credential_id: str, master_password: str) -> Optional[Tuple[str, str]]:
        payload = self._decrypt_payload(master_password)
        if payload is None:
            return None
        items = payload.get("items")
        if not isinstance(items, list):
            return None
        it = self._find_item(items, credential_id)
        if not it:
            return None
        return str(it["api_key"]).strip(), str(it["api_secret"]).strip()

    def get_pair_for_active(self, master_password: str) -> Optional[Tuple[str, str]]:
        """Resolve active id, or the only stored credential, or first in list."""
        pubs = self.list_public_credentials()
        if not pubs:
            return None
        aid = self.get_active_credential_id()
        if aid:
            pair = self.get_secret_pair(aid, master_password)
            if pair:
                return pair
        if len(pubs) == 1:
            self.set_active_credential_id(pubs[0]["id"])
            return self.get_secret_pair(pubs[0]["id"], master_password)
        first = pubs[0]["id"]
        self.set_active_credential_id(first)
        return self.get_secret_pair(first, master_password)

    def save_credentials(self, api_key: str, api_secret: str, master_password: str) -> None:
        """Backward-compatible: replace vault with a single credential."""
        self.validate_master_password_strength(master_password)
        cid = str(uuid.uuid4())
        payload = {
            "v": 2,
            "items": [
                {
                    "id": cid,
                    "api_key": api_key.strip(),
                    "api_secret": api_secret.strip(),
                }
            ],
        }
        self._encrypt_and_write(payload, master_password)
        self.set_active_credential_id(cid)

    def load_credentials(self, master_password: str) -> Optional[Tuple[str, str]]:
        """Return first pair (compat) or active/first resolved pair."""
        pair = self.get_pair_for_active(master_password)
        return pair

    def clear_credentials(self) -> None:
        for p in (self._cred_path, self._salt_path, self._manifest_path, self._active_path):
            if p.is_file():
                p.unlink()
