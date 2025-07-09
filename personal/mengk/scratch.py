# autoflake: skip_file
# pyright: ignore

# %%

import IPython

IPython.get_ipython().run_line_magic("load_ext", "autoreload")
IPython.get_ipython().run_line_magic("autoreload", "2")


# %%


x = """alexander.bondarenko@palisaderesearch.org
yskim23@etri.re.kr
gabriele.sarti996@gmail.com
isidoredmiller@gmail.com
an1kumar@gmail.com
robert.amanfu@gmail.com
qiutianyi.qty@gmail.com
conroy.james@icloud.com
0evanli0@gmail.com
lisabdunlap@berkeley.edu
tuesday@artifex.fun
bo.yan@csiro.au
soniamurthy@g.harvard.edu
tkukurin@gmail.com
xrpatrick@gmail.com
wqchen1024@gmail.com
jerome.wynne@dsit.gov.uk
sid.black@dsit.gov.uk
jrhmann@proton.me
charles@meridianlabs.ai
mrpfisher@gmail.com
hanavmw13@gmail.com
joseph.bloom@dsit.gov.uk
matt.stack@aeonnovafuturelabs.com
stephanie.kasaon@actionlab.africa
alexdzelmartin@gmail.com"""

print(",".join(x.split()))
len(x.split())

# %%
