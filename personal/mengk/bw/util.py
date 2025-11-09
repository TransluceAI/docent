from typing import Any
import pandas as pd

def dql_to_df(cols: list[str], rows: list[list[Any]]):
    def _cast_value(v: Any) -> Any:
        """Cast a value to int, float, bool, or str as appropriate."""
        if v is None:
            return None
        if isinstance(v, (bool, int, float)):
            return v
        
        # Try int
        try:
            if '.' not in v:
                return int(v)
        except (ValueError, TypeError):
            pass

        # Try float
        try:
            return float(v)
        except (ValueError, TypeError):
            pass

        # Keep as original
        return v

    dicts: list[dict[str, Any]] = []
    for row in rows:
        combo = list(zip(cols, row))
        combo = {k: _cast_value(v) for k, v in combo}
        dicts.append(combo)

    return pd.DataFrame(dicts)
