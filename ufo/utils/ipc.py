
from pydantic import BaseModel


class UfoTaskResult(BaseModel):
    status: str  # "success" or "error"
    task_id: str
    output: str | None = None
    error_type: str | None = None
    error_message: str | None = None
    traceback: str | None = None
