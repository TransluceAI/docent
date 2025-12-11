"""{{DESCRIPTION}}"""

# README
# - Requires `pip install docent-python pandas`
# - API key is prefilled; rotate in Docent if you regenerate keys.
# - Run directly with `python <this file>`.

from __future__ import annotations

from docent import Docent

API_KEY = "{{API_KEY}}"
SERVER_URL = "{{SERVER_URL}}"
COLLECTION_ID = "{{COLLECTION_ID}}"

DQL_QUERY = """{{DQL_QUERY}}"""


def main() -> None:
    client = Docent(api_key=API_KEY, server_url=SERVER_URL)

    result = client.execute_dql(COLLECTION_ID, DQL_QUERY)
    df = client.dql_result_to_df_experimental(result)

    print(df.head())
    print(f"Fetched {len(df)} rows")


if __name__ == "__main__":
    main()
