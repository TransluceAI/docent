from __future__ import annotations

import argparse
import json
import random
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Semaphore, local

from tqdm import tqdm

from docent import Docent
from docent.data_models.agent_run import AgentRun
from docent_core._env_util import ENV

_THREAD_LOCAL = local()


def _get_docent(server_url: str) -> Docent:
    doc = getattr(_THREAD_LOCAL, "docent", None)
    if doc is None:
        doc = Docent(server_url=server_url)
        _THREAD_LOCAL.docent = doc
    return doc


def _fetch_agent_run(
    server_url: str, collection_id: str, agent_run_id: str, semaphore: Semaphore
) -> AgentRun | None:
    with semaphore:
        docent_client = _get_docent(server_url)
        return docent_client.get_agent_run(collection_id, agent_run_id)


def main(
    collection_id: str,
    sample_to: int | None = None,
    max_concurrency: int = 25,
    output_path: str = "agent_runs_gitignore.json",
):
    server_url = ENV.get("NEXT_PUBLIC_API_HOST")
    if not server_url:
        raise ValueError("NEXT_PUBLIC_API_HOST is not set")

    docent_client = _get_docent(server_url)

    ids = docent_client.list_agent_run_ids(collection_id)

    if sample_to is not None and sample_to < len(ids):
        ids = random.sample(ids, sample_to)

    print(f"getting {len(ids)} agent runs")
    out: dict[str, AgentRun] = {}

    semaphore = Semaphore(max_concurrency)

    with ThreadPoolExecutor(max_workers=max_concurrency) as executor:
        futures = {
            executor.submit(
                _fetch_agent_run, server_url, collection_id, agent_run_id, semaphore
            ): agent_run_id
            for agent_run_id in ids
        }

        for future in tqdm(as_completed(futures), total=len(futures)):
            agent_run_id = futures[future]
            try:
                agent_run = future.result()
            except Exception as exc:
                print(f"error fetching {agent_run_id}: {exc}")
                continue

            if agent_run is not None:
                out[agent_run_id] = agent_run

    out_prc = [json.loads(item.model_dump_json()) for item in out.values()]

    with open(output_path, "w") as f:
        json.dump(out_prc, f)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download agent runs from a collection")
    parser.add_argument("collection_id", help="Collection identifier to download")
    parser.add_argument(
        "--sample-to",
        type=int,
        default=None,
        help="Randomly sample down to this many agent runs before downloading",
    )
    parser.add_argument(
        "--max-concurrency",
        type=int,
        default=25,
        help="Maximum number of concurrent requests",
    )
    parser.add_argument(
        "--output",
        default="agent_runs_gitignore.json",
        help="Path for the downloaded agent runs JSON",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = _parse_args()
    main(
        args.collection_id,
        sample_to=args.sample_to,
        max_concurrency=args.max_concurrency,
        output_path=args.output,
    )
