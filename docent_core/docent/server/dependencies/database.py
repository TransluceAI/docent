from typing import AsyncContextManager, AsyncGenerator, Callable

from fastapi import Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from docent_core._db_service.db import DocentDB
from docent_core.docent.services.monoservice import MonoService


async def get_db() -> DocentDB:
    return await DocentDB.init()


async def get_mono_svc() -> MonoService:
    return await MonoService.init()


async def get_session(db: DocentDB = Depends(get_db)) -> AsyncGenerator[AsyncSession, None]:
    async with db.session() as session:
        yield session


async def get_session_cm_factory(
    db: DocentDB = Depends(get_db),
) -> Callable[[], AsyncContextManager[AsyncSession]]:
    return db.session


async def require_collection_exists(collection_id: str, db: MonoService = Depends(get_mono_svc)):
    if not await db.collection_exists(collection_id):
        raise HTTPException(status_code=404, detail=f"Collection {collection_id} not found")

    return collection_id
