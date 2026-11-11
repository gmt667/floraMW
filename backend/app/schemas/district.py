from typing import List, Dict
from pydantic import BaseModel, ConfigDict


class DistrictOut(BaseModel):
    id: int
    name: str
    region: str

    model_config = ConfigDict(from_attributes=True)


class DistrictListResponse(BaseModel):
    total: int
    items: List[DistrictOut]
    by_region: Dict[str, List[str]]

