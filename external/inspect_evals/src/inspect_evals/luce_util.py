from pydantic import BaseModel


class LuceTaskArgs(BaseModel):
    task_id: str
    solver_system_message: str
    solver_max_messages: int
