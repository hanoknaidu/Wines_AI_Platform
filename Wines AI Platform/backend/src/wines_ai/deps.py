"""Request-scoped dependencies."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Request

from .config import Settings, get_settings
from .errors import age_not_confirmed, dataset_unavailable
from .services.container import Services


def get_services(request: Request) -> Services:
    return request.app.state.services


def current_user_id(request: Request) -> str:
    """The anonymous session id minted by the session middleware.

    FR-12: many concurrent anonymous sessions, no sign-up. Phase 2 accounts replace
    this one function and nothing else.
    """
    return request.state.user_id


def require_age_confirmed(request: Request) -> None:
    if not getattr(request.state, "age_confirmed", False):
        raise age_not_confirmed()


def require_dataset(services: Annotated[Services, Depends(get_services)]) -> Services:
    if not services.ready:
        raise dataset_unavailable()
    return services


SettingsDep = Annotated[Settings, Depends(get_settings)]
ServicesDep = Annotated[Services, Depends(get_services)]
ReadyServicesDep = Annotated[Services, Depends(require_dataset)]
UserDep = Annotated[str, Depends(current_user_id)]
AgeGate = Depends(require_age_confirmed)
