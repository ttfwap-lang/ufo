from pydantic import BaseModel
from typing import Optional

class UfoTaskResult(BaseModel):
    status: str  # "success" or "error"
    task_id: str
    output: Optional[str] = None
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    traceback: Optional[str] = None
