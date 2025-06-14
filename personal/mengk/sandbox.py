# autoflake: skip_file
# pyright: ignore


# %%

from docent.data_models.citation import (
    parse_citations_multi_run,
    parse_citations_single_run,
)

text = "This is a test [R1T1B1-R1T1B2], [T1B1] and [T1B2, T1B3]"

parse_citations_multi_run(text)


# %%

parse_citations_single_run(text)

# %%


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

ctx = await db.get_default_view_ctx(fgs[0].id)
run = await db.get_any_agent_run(ctx)
print(run.text)

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
