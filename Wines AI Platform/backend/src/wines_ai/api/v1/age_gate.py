"""FR-1: confirm legal drinking age before any recommendation is shown."""

from __future__ import annotations

from fastapi import APIRouter, Request, Response
from itsdangerous import URLSafeSerializer

from ...deps import SettingsDep, UserDep
from ...errors import ApiProblem
from ...schemas import AgeGateRequest

router = APIRouter(tags=["age-gate"])


@router.post("/age-gate", status_code=204)
async def confirm(
    body: AgeGateRequest,
    request: Request,
    settings: SettingsDep,
    user_id: UserDep,
) -> Response:
    if not body.confirmed:
        raise ApiProblem(
            400,
            "age_not_confirmed",
            "Age confirmation required",
            "Confirmation must be explicit.",
        )

    signer = URLSafeSerializer(settings.cookie_secret, salt="wines-ai")
    out = Response(status_code=204)
    # Bound to this session id, so a cookie lifted from another browser does not pass.
    out.set_cookie(
        settings.age_cookie_name,
        signer.dumps(user_id),
        max_age=settings.cookie_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    # The session cookie is minted by middleware on the way out; if this is the very
    # first request it has not been set yet, so set it here too or the age cookie
    # would reference a session the client never receives.
    out.set_cookie(
        settings.session_cookie_name,
        signer.dumps(user_id),
        max_age=settings.cookie_max_age_seconds,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
    )
    return out
