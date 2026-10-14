from datetime import date
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator, model_validator

from price_service.domain import Ticker


class TickerQuery(BaseModel):
    ticker: Ticker

    @field_validator("ticker", mode="before")
    @classmethod
    def normalize_ticker(cls, value: object) -> object:
        return value.lower() if isinstance(value, str) else value


class PriceQuery(TickerQuery):
    limit: int | None = Field(default=None, ge=1, le=10000)
    offset: int = Field(default=0, ge=0)


class HistoryQuery(PriceQuery):
    date_from: date = Field(description="First calendar day, inclusive, UTC (YYYY-MM-DD)")
    date_to: date = Field(description="Last calendar day, inclusive, UTC (YYYY-MM-DD)")

    @field_validator("date_from", "date_to", mode="before")
    @classmethod
    def validate_date_format(cls, value: object) -> object:
        if isinstance(value, str):
            if len(value) != 10 or value[4] != "-" or value[7] != "-":
                raise ValueError("Date must use YYYY-MM-DD")
            return date.fromisoformat(value)
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "HistoryQuery":
        if self.date_from > self.date_to:
            raise ValueError("date_from must not be after date_to")
        if self.date_from < date(1970, 1, 1) or self.date_to == date.max:
            raise ValueError("Dates must be between 1970-01-01 and 9999-12-30")
        return self


class PriceResponse(BaseModel):
    ticker: Ticker
    price: Decimal = Field(description="Exact decimal price, serialized as a JSON string")
    timestamp: int = Field(description="Observation time: UNIX timestamp in seconds, UTC")
