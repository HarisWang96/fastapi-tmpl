"""Async client for a policy decision point (authz-svc)."""

from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field, ValidationError

from app.errors import ServiceUnavailableError


class Decision(BaseModel):
    allow: bool
    reason: str = ""
    version: int = 0


class DataScope(BaseModel):
    mode: Literal["ALL", "IN", "NONE"]
    dimension: str
    column: str | None = None
    values: list[int | str] = Field(default_factory=list)

    def filter_values(self) -> list[int | str] | None:
        return None if self.mode == "ALL" else self.values


class AuthzClient:
    def __init__(self, base_url: str, token: str, timeout: float = 3) -> None:
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"X-Internal-Token": token},
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def check(self, *, user_id: int, app_id: str, perm_code: str) -> Decision:
        data = await self._post(
            "/authz/check",
            {"user_id": user_id, "app_id": app_id, "perm_code": perm_code},
        )
        return self._parse(Decision, data)

    async def scope(
        self, *, user_id: int, app_id: str, resource_key: str, dimension: str
    ) -> DataScope:
        data = await self._post(
            "/authz/scope",
            {
                "user_id": user_id,
                "app_id": app_id,
                "resource_key": resource_key,
                "dimension": dimension,
            },
        )
        return self._parse(DataScope, data)

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ServiceUnavailableError("Authorization service unavailable") from exc
        data = body.get("data") if isinstance(body, dict) else None
        if (
            not isinstance(body, dict)
            or body.get("code") != 200
            or not isinstance(data, dict)
        ):
            raise ServiceUnavailableError("Invalid authorization service response")
        return data

    @staticmethod
    def _parse[T: BaseModel](model: type[T], data: dict[str, Any]) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            raise ServiceUnavailableError(
                "Invalid authorization service response"
            ) from exc
