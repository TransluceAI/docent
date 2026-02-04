from typing import TypedDict

from fastapi import APIRouter

from docent_core._server._rest.onboarding import onboarding_router
from docent_core.docent.server.rest.chart import chart_router
from docent_core.docent.server.rest.chat import chat_router
from docent_core.docent.server.rest.code_samples import code_samples_router
from docent_core.docent.server.rest.data_table import data_table_router
from docent_core.docent.server.rest.dql import dql_router
from docent_core.docent.server.rest.label import label_router
from docent_core.docent.server.rest.refinement import refinement_router
from docent_core.docent.server.rest.result_set import result_set_router
from docent_core.docent.server.rest.router import public_router, user_router
from docent_core.docent.server.rest.rubric import rubric_router
from docent_core.docent.server.rest.settings import settings_router
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
        "router": rubric_router,
        "prefix": "/rest/rubric",
    },
    {
        "router": result_set_router,
        "prefix": "/rest/results",
    },
    {
        "router": label_router,
        "prefix": "/rest/label",
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
        "router": chat_router,
        "prefix": "/rest/chat",
    },
    {
        "router": data_table_router,
        "prefix": "/rest/data-table",
    },
    {
        "router": dql_router,
        "prefix": "/rest/dql",
    },
    {
        "router": code_samples_router,
        "prefix": "/rest/code-samples",
    },
    {
        "router": onboarding_router,
        "prefix": "/rest",
    },
    {
        "router": settings_router,
        "prefix": "/rest/settings",
    },
]

__all__ = ["REST_ROUTERS"]
