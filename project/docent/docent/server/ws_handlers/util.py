from datetime import datetime, timedelta
from typing import Any, Dict

from fastapi import WebSocket
from llm_util.anthropic import is_anthropic_api_key_valid
from llm_util.openai import is_openai_api_key_valid
from llm_util.types import LLMApiKeys
from pydantic import BaseModel


class WSMessage(BaseModel):
    """
    Base schema for incoming messages:
    {
       "action": str,
       "payload": dict
    }
    """

    action: str
    payload: dict[str, Any]


class ConnectionManager:
    def __init__(self, idle_timeout_seconds: int = 1000):
        self.active_connections: Dict[str, set[WebSocket]] = {}  # session_id -> set of websockets
        self.last_activity: Dict[WebSocket, datetime] = {}  # websocket -> last activity timestamp
        self.idle_timeout = timedelta(seconds=idle_timeout_seconds)
        self.api_keys: Dict[str, LLMApiKeys] = {}

    def register(self, session_id: str, websocket: WebSocket):
        self.active_connections.setdefault(session_id, set()).add(websocket)
        self.last_activity[websocket] = datetime.now()
        if session_id not in self.api_keys:
            self.api_keys[session_id] = LLMApiKeys(openai_key=None, anthropic_key=None)

    def disconnect(self, session_id: str, websocket: WebSocket):
        if session_id in self.active_connections:
            self.active_connections[session_id].remove(websocket)
            if not self.active_connections[session_id]:
                del self.active_connections[session_id]
                # Clean up API keys when session is empty
                if session_id in self.api_keys:
                    del self.api_keys[session_id]
        if websocket in self.last_activity:
            del self.last_activity[websocket]

    async def set_api_keys(
        self, session_id: str, anthropic_key: str | None = None, openai_key: str | None = None
    ):
        if anthropic_key:
            if not await is_anthropic_api_key_valid(anthropic_key):
                raise ValueError("Invalid Anthropic API key")
        if openai_key:
            if not await is_openai_api_key_valid(openai_key):
                raise ValueError("Invalid OpenAI API key")

        self.api_keys[session_id] = LLMApiKeys(openai_key=openai_key, anthropic_key=anthropic_key)

    def get_api_keys(self, session_id: str) -> LLMApiKeys:
        return self.api_keys.get(session_id, LLMApiKeys(openai_key=None, anthropic_key=None))

    async def broadcast(self, session_id: str, message: WSMessage):
        if session_id in self.active_connections:
            # Create a list of failed connections to remove after broadcasting
            failed_connections: set[WebSocket] = set()

            for connection in self.active_connections[session_id]:
                try:
                    await connection.send_json(message.model_dump_json())
                except Exception:
                    failed_connections.add(connection)

            # Clean up any failed connections
            for failed in failed_connections:
                self.active_connections[session_id].remove(failed)
                if failed in self.last_activity:
                    del self.last_activity[failed]

    async def send(self, websocket: WebSocket, message: WSMessage):
        await websocket.send_json(message.model_dump())
