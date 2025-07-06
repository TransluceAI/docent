from fastapi import APIRouter, Depends

from docent_core._server._dependencies.user import get_user_anonymous_ok

diff_router = APIRouter(dependencies=[Depends(get_user_anonymous_ok)])


@diff_router.get("/ping")
def ping():
    return "pong"
