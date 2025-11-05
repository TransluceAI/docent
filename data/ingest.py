"""
Ingest functionality using the Docent Python SDK.

Handles ingesting data files by parsing them with appropriate importers
and uploading the data via the Docent SDK.
"""

import os

import httpx
from rich.console import Console

from .cache import ensure_file_available
from .importers import get_importer, parse_filename
from .utils import (
    get_server_host,
    log_error,
    log_info,
    log_success,
    log_warning,
    simple_progress,
)

console = Console()

# Constants
TEST_USER_EMAIL = "test@transluce.org"
TEST_USER_PASSWORD = "password"
DEFAULT_API_KEY_NAME = "data-registry-auto"
DEFAULT_WEB_URL = "http://localhost:3000"


async def ensure_api_key() -> str:
    """
    Ensure DOCENT_API_KEY is set. If not, offer to register a test user.

    Returns:
        The API key to use
    """
    api_key = os.getenv("DOCENT_API_KEY")
    if api_key:
        return api_key

    log_warning("DOCENT_API_KEY environment variable not set.")

    from rich.prompt import Confirm

    if not Confirm.ask("Register test user (test@transluce.org) and create API key?"):
        raise ValueError("API key required for ingestion")

    # Register user and create API key
    api_key = await register_test_user_and_create_api_key()
    log_success("Created API key. Set this environment variable:")
    console.print(f"[bold]DOCENT_API_KEY={api_key}[/bold]\n")

    return api_key


async def register_test_user_and_create_api_key() -> str:
    """
    Register test@transluce.org user and create an API key.

    Returns:
        The created API key
    """
    # Get server host from environment
    server_host = get_server_host()

    async with httpx.AsyncClient() as client:
        # First, try to register the user
        register_data = {"email": TEST_USER_EMAIL, "password": TEST_USER_PASSWORD}

        try:
            register_response = await client.post(f"{server_host}/rest/signup", json=register_data)

            if register_response.status_code not in [200, 201, 409]:  # 409 = user already exists
                raise ValueError(f"Failed to register user: {register_response.text}")

        except httpx.RequestError as e:
            raise ValueError(f"Failed to connect to Docent server at {server_host}: {e}")

        # Login to get session
        login_response = await client.post(f"{server_host}/rest/login", json=register_data)

        if login_response.status_code != 200:
            raise ValueError(f"Failed to login: {login_response.text}")

        # Create API key
        api_key_data = {"name": DEFAULT_API_KEY_NAME}

        api_key_response = await client.post(f"{server_host}/rest/api-keys", json=api_key_data)

        if api_key_response.status_code not in [200, 201]:
            raise ValueError(f"Failed to create API key: {api_key_response.text}")

        response_data = api_key_response.json()
        return response_data["api_key"]


async def ingest_file(filename: str, importer_override: str | None = None) -> None:
    """
    Ingest a file using the Docent Python SDK.

    Args:
        filename: Name of the file to ingest (will be downloaded from S3 if needed)
        importer_override: Override importer to use
    """
    # Ensure API key is available
    api_key = await ensure_api_key()

    # Set environment variable for docent SDK
    os.environ["DOCENT_API_KEY"] = api_key

    # Import docent SDK after setting API key
    import docent

    # Ensure the file is available locally, downloading if needed
    try:
        local_path = await ensure_file_available(filename)
    except ValueError as e:
        log_error(f"Could not obtain file '{filename}': {e}")
        raise

    # Parse filename to get collection name and importer (unless overridden)
    try:
        collection_name, parsed_importer_name, _ = parse_filename(filename)
        importer_name = importer_override or parsed_importer_name
    except ValueError as e:
        log_error(str(e))
        raise

    log_info(f"Processing {filename}:")
    console.print(f"  Collection: {collection_name}")
    console.print(f"  Importer: {importer_name}")

    server_url = get_server_host()

    log_info(f"Using Docent server at: {server_url}")

    # Create or get collection
    with simple_progress("Creating collection..."):
        try:
            client = docent.Docent(
                server_url=server_url,
                web_url=DEFAULT_WEB_URL,
            )
            collection_id = client.create_collection(name=collection_name)

            log_success(f"Created/found collection: '{collection_name}' (ID: {collection_id})")

        except Exception as e:
            log_error("Failed to create collection", e)
            raise

    for _ in range(1):  # NOTE(mengk): added this to enable simulation of "very large" collections.
        # Get the appropriate importer
        try:
            importer_func = get_importer(importer_name)
        except ValueError as e:
            log_error(str(e))
            raise

        # Process the file to get agent runs
        with simple_progress("Processing file..."):
            try:
                agent_runs, file_info = await importer_func(local_path)

                log_success(
                    f"Processed {len(agent_runs)} agent runs from {file_info.get('filename', filename)}"
                )

            except Exception as e:
                log_error(f"Failed to process file '{filename}'", e)
                raise

        # Upload agent runs
        log_info(f"Uploading {len(agent_runs)} agent runs...")

        try:
            client.add_agent_runs(collection_id, agent_runs, batch_size=250)
            log_success(
                f"Successfully uploaded {len(agent_runs)} agent runs to collection '{collection_name}'"
            )

        except Exception as e:
            log_error("Failed to upload agent runs", e)
            raise
