import time
from contextlib import asynccontextmanager
from typing import Any, Awaitable, Callable

import anyio
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.base import BaseHTTPMiddleware

from docent._log_util import get_logger
from docent_core._env_util import ENV
from docent_core._server._auth.session_middleware import SessionAuthMiddleware
from docent_core._server._broker.router import broker_router
from docent_core._server._rest._all_routers import REST_ROUTERS

logger = get_logger(__name__)


def get_cors_configuration() -> dict[str, Any]:
    """
    Get CORS configuration for both development and production environments.

    **Environment-based CORS behavior:**

    **Development Mode** (DOCENT_CORS_ORIGINS empty/unset):
    - Uses regex pattern to allow any localhost port
    - Supports localhost, 127.0.0.1, and 0.0.0.0 with any port
    - Works with both HTTP and HTTPS protocols
    - Examples: http://localhost:3000, https://127.0.0.1:8080

    **Production Mode** (DOCENT_CORS_ORIGINS set with values):
    - Uses exact origin matching for maximum security
    - Comma-separated list of allowed origins
    - Validates and strips whitespace from each origin
    - Examples: https://yourdomain.com or https://app.yourdomain.com,https://admin.yourdomain.com

    Returns:
        Dictionary with CORS middleware configuration parameters
    """
    # Read CORS origins from environment variable
    cors_origins_env = ENV.get("DOCENT_CORS_ORIGINS")

    # Check if environment variable is set and contains valid origins
    if cors_origins_env and cors_origins_env.strip():
        # Production mode: Parse and validate exact origins
        origins = [origin.strip() for origin in cors_origins_env.split(",") if origin.strip()]

        # Validate that we have at least one valid origin
        if not origins:
            logger.warning(
                "DOCENT_CORS_ORIGINS is set but contains no valid origins. "
                "Falling back to development mode with localhost regex."
            )
            return _get_development_cors_config()

        # Log production configuration
        logger.info(f"🔒 Production CORS mode: Using exact origins {origins}")
        return {
            "allow_origins": origins,
            "allow_credentials": True,
            "allow_methods": ["*"],
            "allow_headers": ["*"],
        }
    else:
        # Development mode: Use regex for flexible localhost support
        logger.info("🔧 Development CORS mode: Using regex pattern for localhost origins")
        return _get_development_cors_config()


def _get_development_cors_config() -> dict[str, Any]:
    """
    Get CORS configuration for development environment using regex pattern.

    **Regex pattern breakdown:**
    ```
    ^https?://(localhost|127\\.0\\.0\\.1|0\\.0\\.0\\.0):\\d+$
    ```

    - `^https?://` - HTTP or HTTPS protocol at start
    - `(localhost|127\\.0\\.0\\.1|0\\.0\\.0\\.0)` - Localhost variations (dots escaped)
    - `:\\d+` - Colon followed by port number (1+ digits)
    - `$` - End of string (prevents subdomain attacks)

    **Allowed origins examples:**
    - ✅ http://localhost:3000
    - ✅ https://localhost:8080
    - ✅ http://127.0.0.1:3001
    - ✅ https://0.0.0.0:4000
    - ❌ http://localhost (no port)
    - ❌ http://evil.localhost:3000 (subdomain)
    - ❌ http://external.com:3000 (external domain)

    Returns:
        Dictionary with development CORS configuration
    """
    development_regex = r"^https?://(localhost|127\.0\.0\.1|0\.0\.0\.0):\d+$"

    return {
        "allow_origin_regex": development_regex,
        "allow_credentials": True,
        "allow_methods": ["*"],
        "allow_headers": ["*"],
    }


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable[[Request], Awaitable[Response]]):
        # Log request details
        start_time = time.perf_counter()
        logger.highlight(f"Started {request.method} {request.url.path}")

        # Process the request
        response = await call_next(request)

        # Log completion time
        process_time = time.perf_counter() - start_time
        logger.highlight(
            f"Completed {request.method} {request.url.path} in {process_time * 1000:.2f}ms"
        )

        return response


async def periodic_cleanup_task():
    """Background task that periodically cleans up old chat sessions."""
    from docent_core._db_service.service import DBService

    while True:
        await anyio.sleep(24 * 3600)  # once a day

        try:
            db = await DBService.init()
            deleted_count = await db.cleanup_old_chat_sessions()
            logger.info(f"Periodic cleanup: deleted {deleted_count} old chat sessions")

        except Exception as e:
            logger.error(f"Error in periodic cleanup task: {e}")
            await anyio.sleep(3600)


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with anyio.create_task_group() as tg:
        tg.start_soon(periodic_cleanup_task)

        yield

        logger.info("Shutting down...")
        tg.cancel_scope.cancel()


asgi_app = FastAPI()  # type: ignore

# Add middlewares in order (they are processed in reverse order when handling responses)
# 1. Request logging middleware first
asgi_app.add_middleware(RequestLoggingMiddleware)
# 2. Session authentication middleware second (after logging, before CORS)
asgi_app.add_middleware(SessionAuthMiddleware)

# Configure CORS with environment-based settings
cors_config = get_cors_configuration()
asgi_app.add_middleware(CORSMiddleware, **cors_config)

# Include broker router
asgi_app.include_router(broker_router, prefix="/broker")
# Include all REST routers (different ones for different features)
for router in REST_ROUTERS:
    asgi_app.include_router(router["router"], prefix=router["prefix"])

# If running in production, add Sentry middleware
# import sentry_sdk
# from sentry_sdk.integrations.asgi import SentryAsgiMiddleware  # type: ignore
# if ENV.ENV_TYPE == "prod" or os.environ.get("ENABLE_SENTRY", False):
#     logger.info("Initializing Sentry for production")
#     sentry_sdk.init(  # type: ignore
#         dsn="https://c5f049f4a74b7cd17fbf688db7f4838a@o4509013218689024.ingest.us.sentry.io/4509013219803136",
#         # Add data like request headers and IP for users,
#         # see https://docs.sentry.io/platforms/python/data-management/data-collected/ for more info
#         send_default_pii=True,
#     )
#     asgi_app.add_middleware(SentryAsgiMiddleware)  # type: ignore


@asgi_app.get("/")
async def root():
    return "clarity has been achieved"
