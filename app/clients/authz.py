"""PDP client for authz-svc.

The gateway owns authentication. Services own fine-grained authorization:
declare a permission code on the route and ask authz-svc whether the caller
holds it. Data scopes are returned as values that the repository converts into
parameterized WHERE clauses; they cannot be evaluated at the gateway because
that requires resource context.
"""

from __future__ import annotations

from typing import Any, Literal

import httpx2
from pydantic import BaseModel, Field, ValidationError

from app.core.exceptions import ServiceUnavailableError
from app.core.logger import logger


class Decision(BaseModel):
    allow: bool
    reason: str
    version: int = 0


class DataScope(BaseModel):
    mode: Literal["ALL", "IN", "NONE"]
    dimension: str
    column: str | None = None
    values: list[int | str] = Field(default_factory=list)
    version: int = 0

    def filter_values(self) -> list[int | str] | None:
        """ALL returns None (no filter); IN returns values; NONE returns [].

        Repositories must treat None as "no WHERE clause" and [] as "no rows";
        every value is still bound with %s, never interpolated into SQL.
        """
        return None if self.mode == "ALL" else self.values


class AuthzClient:
    """Thin async HTTP client. One instance per process, closed on shutdown."""

    def __init__(
        self,
        *,
        base_url: str,
        internal_token: str,
        timeout: float,
        transport: httpx2.AsyncBaseTransport | None = None,
    ) -> None:
        self._client = httpx2.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout,
            headers={"X-Internal-Token": internal_token},
            transport=transport,
        )

    async def check(
        self,
        *,
        user_id: int,
        app_id: str,
        perm_code: str,
        active_dept_id: int | None = None,
    ) -> Decision:
        payload: dict[str, Any] = {
            "app_id": app_id,
            "user_id": user_id,
            "perm_code": perm_code,
        }
        if active_dept_id is not None:
            payload["active_dept_id"] = active_dept_id
        data = await self._post("/authz/check", payload)
        return self._parse(Decision, data, "check")

    async def scope(
        self,
        *,
        user_id: int,
        app_id: str,
        resource_key: str,
        dimension: str,
        active_dept_id: int | None = None,
    ) -> DataScope:
        payload: dict[str, Any] = {
            "app_id": app_id,
            "user_id": user_id,
            "resource_key": resource_key,
            "dimension": dimension,
        }
        if active_dept_id is not None:
            payload["active_dept_id"] = active_dept_id
        data = await self._post("/authz/scope", payload)
        return self._parse(DataScope, data, "scope")

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        try:
            response = await self._client.post(path, json=payload)
            response.raise_for_status()
            body = response.json()
        except (httpx2.HTTPError, ValueError) as exc:
            # Fail closed: an authorization dependency that cannot answer must
            # not turn into an allow. 503 lets the caller retry or alert.
            logger.error(f"authz 调用失败 path={path} error={type(exc).__name__}")
            raise ServiceUnavailableError("权限服务不可用") from exc

        data = body.get("data") if isinstance(body, dict) else None
        if not isinstance(body, dict) or body.get("code") != 200 or not isinstance(data, dict):
            code = body.get("code") if isinstance(body, dict) else "-"
            logger.error(f"authz 返回异常 path={path} code={code}")
            raise ServiceUnavailableError("权限服务返回异常")
        return data

    @staticmethod
    def _parse[T: BaseModel](model: type[T], data: dict[str, Any], action: str) -> T:
        try:
            return model.model_validate(data)
        except ValidationError as exc:
            logger.error(f"authz 响应格式错误 action={action}")
            raise ServiceUnavailableError("权限服务返回异常") from exc
