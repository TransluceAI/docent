from fastapi import Depends, HTTPException

from docent_core._db_service.service import DBService


async def get_db() -> DBService:
    # DBService is a singleton, so we can just return the instance
    return await DBService.init()


async def require_collection_exists(collection_id: str, db: DBService = Depends(get_db)):
    if not await db.fg_exists(collection_id):
        raise HTTPException(status_code=404, detail=f"Collection {collection_id} not found")

    return collection_id
