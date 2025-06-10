# autoflake: skip_file
# pyright: ignore

# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")
IPython.get_ipython().run_line_magic("autoreload", "2")

# %%

from docent._db_service.service import DBService

db = await DBService.init()


# %%


await db.get_users()


# %%

fgs = await db.get_fgs()
fgs


# %%

from docent._db_service.schemas.auth_models import Permission, ResourceType, SubjectType

fg_id = fgs[1].id
await db.set_acl_permission(
    SubjectType.PUBLIC, "*", ResourceType.FRAME_GRID, fg_id, Permission.READ
)
views = await db.get_all_view_ctxs(fg_id)
for view in views:
    await db.set_acl_permission(
        SubjectType.PUBLIC, "*", ResourceType.VIEW, view.view_id, Permission.READ
    )


# %%

ctx = await db.get_default_view_ctx(fg_id)

# %%

ctx

# %%


fg_id = "677791bc-0891-4605-9cfa-150e6187543d"
run = await db.get_any_agent_run(ctx)
