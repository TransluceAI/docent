from morphcloud.api import MorphCloudClient, Instance

client = MorphCloudClient()
TASK_CONFIG_TO_INSTANCE: dict[str, Instance] = {}

import time


def create_docker_snapshot(memory_gb: int, disk_gb: int, num_cpus: int) -> str:
    start = time.time()
    snapshot_id = client.snapshots.create(
        vcpus=num_cpus, memory=1024 * memory_gb, disk_size=1024 * disk_gb
    ).id
    print(f"created plain snapshot in {time.time() - start}s")
    start = time.time()
    instance = client.instances.start(snapshot_id=snapshot_id)
    print(f"created instance in {time.time() - start}s")
    start = time.time()
    instance.exec(
        [
            "apt update -y && apt install -y docker.io && systemctl enable docker && systemctl start docker"
        ]
    )
    print(f"executed setup on instance in {time.time() - start}s")
    new_snapshot_id = instance.snapshot().id

    instance.stop()

    return new_snapshot_id


def generate_intercode_snapshot():
    print(create_docker_snapshot(memory_gb=8, disk_gb=8, num_cpus=1))
    # use the snapshot id in docker.py task_init
    # MORPH_API_KEY=... inspect eval inspect_evals/luce_intercode_ctf --model openai/gpt-4o --epochs=1 --log-dir=/home/ubuntu/artifacts/vincent/inspect --sample-id=2


def generate_base_cybench_snapshot():
    print(create_docker_snapshot(memory_gb=16, disk_gb=16, num_cpus=1))
    # use the snapshot id in docker.py task_init
    # MORPH_API_KEY=... inspect eval inspect_evals/cybench --model anthropic/claude-3-5-sonnet-latest -T challenges=its_so_joever --epochs=1 --log-dir=/home/ubuntu/artifacts/vincent/inspect


def generate_all_cybench_snapshots():
    # use the base cybench snapshot for every other task
    # MORPH_API_KEY=... inspect eval inspect_evals/cybench --model anthropic/claude-3-5-sonnet-latest --epochs=1 --log-dir=/home/ubuntu/artifacts/vincent/inspect
    pass


def generate_chunky_hard_snapshot():
    # chunky requires 24GB instead of 16GB disk space, so we should regenerate from scratch
    print(create_docker_snapshot(memory_gb=16, disk_gb=24, num_cpus=4))
    # use the snapshot id in docker.py task_init
    # MORPH_API_KEY=... inspect eval inspect_evals/cybench --model anthropic/claude-3-5-sonnet-latest -T challenges=chunky --epochs=1 --log-dir=/home/ubuntu/artifacts/vincent/inspect


# afterwards you shouldl be able to run all of cybench concurrently! eg.
# MORPH_API_KEY=... inspect eval inspect_evals/cybench --model anthropic/claude-3-5-sonnet-latest --epochs=1 --log-dir=/home/ubuntu/artifacts/vincent/inspect --max-connections=64
