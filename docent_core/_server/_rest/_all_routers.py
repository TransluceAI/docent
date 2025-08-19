from typing import TypedDict

from fastapi import APIRouter

from docent_core._server._rest.onboarding import onboarding_router
from docent_core._server._rest.refinement import refinement_router
from docent_core.docent.server.rest.chart import chart_router
from docent_core.docent.server.rest.diff import diff_router
from docent_core.docent.server.rest.router import public_router, user_router
from docent_core.docent.server.rest.rubric import rubric_router
from docent_core.docent.server.rest.telemetry import telemetry_router


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
    {
        "router": telemetry_router,
        "prefix": "/rest/telemetry",
    },
    {
        "router": refinement_router,
        "prefix": "/rest/refinement",
    },
    {
        "router": chart_router,
        "prefix": "/rest/chart",
    },
    {
        "router": onboarding_router,
        "prefix": "/rest",
    },
]

__all__ = ["REST_ROUTERS"]
