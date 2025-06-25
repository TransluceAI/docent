from fastapi import Depends, HTTPException

from docent._db_service.service import DBService


async def get_db() -> DBService:
    # DBService is a singleton, so we can just return the instance
    return await DBService.init()


async def require_fg_exists(fg_id: str, db: DBService = Depends(get_db)):
    if not await db.fg_exists(fg_id):
        raise HTTPException(status_code=404, detail=f"Framegrid {fg_id} not found")

    return fg_id
