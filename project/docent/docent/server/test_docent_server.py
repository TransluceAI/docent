import asyncio
import json
import random
from dataclasses import dataclass
from typing import Any, Literal

import websockets.client


@dataclass
class WSMessage:
    action: str
    payload: dict[str, Any]

    def to_json(self) -> str:
        return json.dumps({"action": self.action, "payload": self.payload})


async def send_message(
    websocket: websockets.client.WebSocketClientProtocol, message: WSMessage
) -> dict[str, Any]:
    await websocket.send(message.to_json())
    response = await websocket.recv()
    return json.loads(response)


import time

STOP_STAGES = Literal[
    "create_session",
    "join_session",
    "get_dimensions",
    "get_datapoint",
    "marginalize",
    "compute_attributes",
]


async def test_docent_server(index: int, stop_stage: STOP_STAGES):
    uri = "wss://docent.neuron-descriptions.net/ws/framegrid"

    start = time.time()

    try:

        async with websockets.client.connect(uri) as websocket:
            if random.random() < 0.05:
                print(f"Connected to server in {time.time() - start} seconds")
            start = time.time()

            # Create a new session
            response = await send_message(
                websocket,
                WSMessage(action="create_session", payload={"eval_ids": ["picoCTF"]}),
            )
            session_id = response["payload"]["id"]
            if random.random() < 0.05:
                print(f"Created session: {session_id} in {time.time() - start} seconds")
            if stop_stage == "create_session":
                return
            start = time.time()

            # Join the session
            response = await send_message(
                websocket, WSMessage(action="join_session", payload={"session_id": session_id})
            )
            if random.random() < 0.05:
                print(f"Joined session in {time.time() - start} seconds")
            if stop_stage == "join_session":
                return

            # Get dimensions
            response = await send_message(websocket, WSMessage(action="get_dimensions", payload={}))
            if random.random() < 0.05:
                print(f"Got dimensions in {time.time() - start} seconds")

            if stop_stage == "get_dimensions":
                return

            # Get a datapoint
            start = time.time()
            response = await send_message(
                websocket,
                WSMessage(
                    action="get_datapoint",
                    payload={
                        "datapoint_id": "inspect_evals_luce_intercode_ctf_0_improved_scaffold_1"
                    },
                ),
            )
            if random.random() < 0.04:
                print(f"Got datapoint in {time.time() - start} seconds")

            if stop_stage == "get_datapoint":
                return

            start = time.time()
            response = await send_message(
                websocket,
                WSMessage(
                    action="marginalize",
                    payload={
                        "keep_dim_ids": ["sample_id", "experiment_id"],
                        "map_type": "stats",
                        "request_type": "exp_stats",
                    },
                ),
            )
            if random.random() < 0.04:
                print(f"Got marginalize in {time.time() - start} seconds")

            if stop_stage == "marginalize":
                return

            start = time.time()

            # Compute attributes for a dimension
            # Send the compute_attributes request
            response = await send_message(
                websocket,
                WSMessage(
                    action="compute_attributes",
                    payload={
                        "attribute": "some things the model did badly" + str(index),
                        "_task_id": "attr_task_1",  # Add task ID to allow tracking/cancellation
                    },
                ),
            )

            # Wait for streaming updates
            updates_received = 0
            while True:
                update = await websocket.recv()
                update_data = json.loads(update)

                if update_data["action"] == "compute_attributes_update":
                    updates_received += 1
                    print(f"{update_data['payload']}")

                # Break when we receive the completion message
                elif update_data["action"] == "compute_attributes_complete":
                    print(f"Attribute computation complete after {updates_received} updates")
                    break

                # Handle other potential messages
                elif update_data["action"] == "error":
                    print(
                        f"Error during attribute computation: {update_data['payload']['message']}"
                    )
                    break
            print(f"Total time taken: {time.time() - start} seconds")
            print(update_data)
    except Exception as e:
        print(f"Failed: {e}")


if __name__ == "__main__":
    import asyncio

    async def run_tests_in_parallel(CONCURRENCY: int, stop_stage: STOP_STAGES):
        """Run multiple test instances in parallel."""
        tasks: list[asyncio.Task] = []
        for i in range(CONCURRENCY):
            tasks.append(asyncio.create_task(test_docent_server(i, stop_stage)))

        await asyncio.gather(*tasks)

    # Run the parallel tests
    asyncio.run(run_tests_in_parallel(CONCURRENCY=10, stop_stage="compute_attributes"))
