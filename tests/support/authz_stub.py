"""Local-only authorization stub for the prod-sim Compose profile."""

import os

import uvicorn
from fastapi import FastAPI, Header, HTTPException

app = FastAPI()
TOKEN = os.environ.get("INTERNAL_API_TOKEN", "")


def _authorize(token: str | None) -> None:
    if not TOKEN or token != TOKEN:
        raise HTTPException(status_code=401)


@app.post("/authz/check")
async def check(payload: dict, x_internal_token: str | None = Header(default=None)):
    _authorize(x_internal_token)
    return {"code": 200, "data": {"allow": True, "reason": "local-test", "version": 1}}


@app.post("/authz/scope")
async def scope(payload: dict, x_internal_token: str | None = Header(default=None)):
    _authorize(x_internal_token)
    return {
        "code": 200,
        "data": {"mode": "IN", "dimension": payload["dimension"], "values": [1]},
    }


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
