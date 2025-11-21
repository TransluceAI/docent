from __future__ import annotations

import asyncio
from typing import Any, AsyncContextManager, Mapping, Protocol, Sequence, cast

import aioboto3
from botocore.exceptions import BotoCoreError, NoCredentialsError

from docent._log_util import get_logger
from docent_core._server._broker.redis_client import get_redis_client

logger = get_logger(__name__)

QUEUE_METRIC_NAMESPACE = "Docent/Workers"
QUEUE_METRIC_NAME = "QueueDepth"
QUEUE_METRIC_DIMENSION_QUEUE = "QueueName"
QUEUE_METRIC_DIMENSION_DEPLOYMENT = "Deployment"
QUEUE_METRIC_INTERVAL_SECONDS = 30
QUEUE_METRIC_RECOVERY_SECONDS = 30


class CloudWatchClient(Protocol):
    async def put_metric_data(
        self,
        *,
        Namespace: str,
        MetricData: Sequence[Mapping[str, Any]],
    ) -> Any: ...


async def queue_depth_metrics_loop(queue_name: str, deployment_id: str | None) -> None:
    """Continuously publish the queue depth for a worker queue to CloudWatch."""
    redis_client = await get_redis_client()
    if deployment_id is None or deployment_id == "local":
        logger.info(
            "Skipping publishing queue depth metrics to CloudWatch for %s because deployment is %s",
            queue_name,
            deployment_id,
        )
        return
    dimensions = [
        {"Name": QUEUE_METRIC_DIMENSION_QUEUE, "Value": queue_name},
        {"Name": QUEUE_METRIC_DIMENSION_DEPLOYMENT, "Value": deployment_id},
    ]
    session = aioboto3.Session()
    while True:
        try:
            client_cm = cast(
                AsyncContextManager[CloudWatchClient],
                cast(Any, session).client("cloudwatch"),
            )
            async with client_cm as cloudwatch:
                logger.info(
                    "Started queue depth metrics publisher for %s (deployment=%s)",
                    queue_name,
                    deployment_id,
                )
                last_reported_depth: int | None = None
                while True:
                    depth = await redis_client.zcard(queue_name)  # type: ignore[arg-type]
                    if last_reported_depth is None or depth != last_reported_depth:
                        logger.info("Queue depth for %s: %s", queue_name, depth)
                    await cloudwatch.put_metric_data(
                        Namespace=QUEUE_METRIC_NAMESPACE,
                        MetricData=[
                            {
                                "MetricName": QUEUE_METRIC_NAME,
                                "Dimensions": dimensions,
                                "Value": int(depth),
                                "Unit": "Count",
                            }
                        ],
                    )
                    last_reported_depth = int(depth)
                    await asyncio.sleep(QUEUE_METRIC_INTERVAL_SECONDS)
        except asyncio.CancelledError:
            raise
        except NoCredentialsError:
            logger.info(
                "AWS credentials unavailable; disabling queue depth metrics for %s",
                queue_name,
            )
            return
        except (BotoCoreError, Exception) as exc:
            logger.warning("Queue depth metrics publisher error for %s: %s", queue_name, exc)
            await asyncio.sleep(QUEUE_METRIC_RECOVERY_SECONDS)
