# pyright: ignore
# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")
IPython.get_ipython().run_line_magic("autoreload", "2")

# %%


db = await DBService.init()

# %%

fg_id = "fa6aa172-e3dd-4cab-b29f-f2c90960b015"
await db.get_attribute_searches_with_judgment_counts(fg_id)

# %%
