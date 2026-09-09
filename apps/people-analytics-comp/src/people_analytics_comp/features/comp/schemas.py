from pydantic import BaseModel


class CompensationRow(BaseModel):
    employee_id: str
    team: str
    base_salary: int
    currency: str
