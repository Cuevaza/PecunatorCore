"""Pydantic payloads for the engine API."""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class VaultSessionBody(BaseModel):
    master_password: str = Field(min_length=12, description="Unlocks credentials.enc")


class GatewayStartBody(BaseModel):
    master_password: Optional[str] = Field(default=None, description="Override or one-shot unlock for gateway start")


class VaultStatusOut(BaseModel):
    vault_file_exists: bool
    credential_rows: int
    active_credential_id: Optional[str]
    session_cached: bool


class GatewaySnapshotOut(BaseModel):
    gateway_running: bool
    last_error: Optional[str]
    account_summary: dict[str, Any]
    balances: list[dict[str, Any]]
    balances_total_assets_in_response: int
    ws_connected: bool
    selected_symbol: str
