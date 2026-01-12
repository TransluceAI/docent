---
name: mengk-personal-test-script
description: Creates test scripts for testing something in mengk's personal folder. For when mengk wants to write a script to test functionality, APIs, or code behavior.
---

# Test Script Creation

## Output Location

Always write test scripts for mengk to the directory: `personal/mengk/cc/`. Create this directory if it doesn't exist.

## Script Modes

### Interactive Mode (Default)

By default, use the interactive format:

1. Use `#%%` cell markers to create Jupyter-style interactive cells
2. Include IPython autoreloading at the top of the script

Start the script with:
```python
#%%
# IPython autoreload setup
try:
    from IPython import get_ipython
    ipython = get_ipython()
    if ipython is not None:
        ipython.run_line_magic("load_ext", "autoreload")
        ipython.run_line_magic("autoreload", "2")
except Exception:
    pass  # Not in IPython environment

#%%
# Your test code here
```

Each logical section should be in its own `#%%` cell.

**Async note:** In interactive mode, you can use `await` directly at the top level. No need for `asyncio.run()`.

### Non-Interactive Mode

If and only if the user explicitly asks for a "non-interactive" or "regular" script:
- Write standard Python without `#%%` markers
- Do NOT include autoreload setup
- Use regular script structure
- For async code, use `asyncio.run()` to execute coroutines

## Naming Convention

Name scripts descriptively based on what they test, e.g.:
- `test_api_endpoints.py`
- `test_model_inference.py`
- `test_data_processing.py`
