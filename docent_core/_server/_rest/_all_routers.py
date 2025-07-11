from typing import TypedDict

from fastapi import APIRouter

from docent_core._server._rest.diff import diff_router
from docent_core._server._rest.router import public_router, user_router
from docent_core._server._rest.rubric import rubric_router


class RouterSpec(TypedDict):
    router: APIRouter
    prefix: str


REST_ROUTERS: list[RouterSpec] = [
    {
        "router": public_router,
        "prefix": "/rest",
    },
    {
        "router": user_router,
        "prefix": "/rest",
    },
    {
        "router": diff_router,
        "prefix": "/rest/diff",
    },
    {
        "router": rubric_router,
        "prefix": "/rest/rubric",
    },
]

__all__ = ["REST_ROUTERS"]
