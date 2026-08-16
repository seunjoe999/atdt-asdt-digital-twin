"""The CDDT cross-domain adapter (thesis Section 2.6): ASDT's only channel
to ATDT is this thin HTTP client — no shared database, no shared secret. It
authenticates every call by forwarding the *student's own* ATDT bearer
token, so from ATDT's point of view a request from ASDT is indistinguishable
from the student calling directly. That is the trust model this MVP uses to
answer "who is entitled to represent a student" (thesis 1.5): ASDT can only
ever act with a capability the student themself already holds. A production
system would likely narrow this to a short-lived, scope-limited token rather
than the student's full session token — documented as a next step in the
README, not implemented here.
"""

from __future__ import annotations

import httpx
from fastapi import HTTPException

from app.config import get_settings


class ATDTError(HTTPException):
    pass


async def whoami(token: str) -> dict:
    """Resolve identity by asking ATDT itself, rather than decoding the
    token locally — ASDT holds no JWT secret at all.
    """
    return await _get("/auth/me", token)


async def get_my_attempts(token: str, course_id: int) -> list[dict]:
    return await _get(f"/courses/{course_id}/examination/my-attempts", token)


async def ask_tutor(token: str, course_id: int, question: str) -> dict:
    return await _post(f"/courses/{course_id}/tutoring/query", token, {"question": question})


async def _get(path: str, token: str) -> dict | list:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.atdt_base_url, timeout=30.0) as client:
        try:
            resp = await client.get(path, headers={"Authorization": f"Bearer {token}"})
        except httpx.RequestError as exc:
            raise ATDTError(status_code=502, detail=f"Could not reach ATDT: {exc}") from exc
    if resp.status_code >= 400:
        raise ATDTError(status_code=resp.status_code, detail=f"ATDT rejected the request: {resp.text}")
    return resp.json()


async def _post(path: str, token: str, body: dict) -> dict:
    settings = get_settings()
    async with httpx.AsyncClient(base_url=settings.atdt_base_url, timeout=30.0) as client:
        try:
            resp = await client.post(path, headers={"Authorization": f"Bearer {token}"}, json=body)
        except httpx.RequestError as exc:
            raise ATDTError(status_code=502, detail=f"Could not reach ATDT: {exc}") from exc
    if resp.status_code >= 400:
        raise ATDTError(status_code=resp.status_code, detail=f"ATDT rejected the request: {resp.text}")
    return resp.json()
