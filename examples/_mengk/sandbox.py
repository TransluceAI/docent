# autoflake: skip_file
# pyright: ignore

# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")
IPython.get_ipython().run_line_magic("autoreload", "2")

# %%

from docent._db_service.service import DBService

db_service = await DBService.init()

# %%


fg_id = "bf7369a0-ee0d-4a0d-be38-a464c6f32c9d"
f = await db_service.get_base_filter(fg_id)
# %%
fd = f.model_dump()
fd
# %%

from docent.data_models.filters import AttributeExistsFilter

fd["filters"].append(
    AttributeExistsFilter(
        attribute="potential issues with the environment the agent is operating in"
    ).model_dump()
)

# %%

from docent.data_models.filters import parse_filter_dict

f_new = parse_filter_dict(fd)


# %%


f_new


# %%
await db_service.set_base_filter(fg_id, f_new)
# %%
