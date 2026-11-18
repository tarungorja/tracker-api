from typing import Annotated

from pydantic import AfterValidator, BaseModel, ConfigDict
from pydantic.alias_generators import to_camel

from app.utils.time import is_valid_date_key


class CamelModel(BaseModel):
    """JSON uses camelCase (matching the UI types); Python code uses snake_case."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


def _check_date_key(value: str) -> str:
    if not is_valid_date_key(value):
        raise ValueError("Invalid date.")
    return value


DateKey = Annotated[str, AfterValidator(_check_date_key)]
"""A "YYYY-MM-DD" calendar date."""


class OkResponse(CamelModel):
    ok: bool = True


class CountResult(OkResponse):
    count: int
