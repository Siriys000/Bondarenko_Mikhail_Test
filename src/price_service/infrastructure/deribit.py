import json
from decimal import Decimal
from typing import Any

import aiohttp
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from price_service.domain import Ticker, UpstreamError


class IndexResult(BaseModel):
    model_config = ConfigDict(extra="ignore")
    index_price: Decimal = Field(gt=0, allow_inf_nan=False, max_digits=28, decimal_places=12)


class IndexResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")
    jsonrpc: str = Field(pattern=r"^2\.0$")
    result: IndexResult


class DeribitClient:
    def __init__(self, session: aiohttp.ClientSession, base_url: str) -> None:
        self._session = session
        self._base_url = base_url.rstrip("/")

    async def get_index_price(self, ticker: Ticker) -> Decimal:
        try:
            async with self._session.get(
                f"{self._base_url}/public/get_index_price", params={"index_name": ticker.value}
            ) as response:
                if response.status != 200:
                    raise UpstreamError(
                        f"Deribit HTTP {response.status}",
                        retryable=response.status in (408, 429) or response.status >= 500,
                    )
                payload: Any = json.loads(await response.text(), parse_float=Decimal)
        except (TimeoutError, aiohttp.ClientError) as exc:
            raise UpstreamError("Deribit network failure", retryable=True) from exc
        except (ValueError, UnicodeError) as exc:
            raise UpstreamError("Deribit returned invalid JSON", retryable=False) from exc

        if isinstance(payload, dict) and "error" in payload:
            error = payload["error"]
            code = error.get("code") if isinstance(error, dict) else None
            raise UpstreamError(
                f"Deribit JSON-RPC error code={code}",
                retryable=code in (10028, 10040, 10066, 11051, 11094),
            )
        try:
            return IndexResponse.model_validate(payload).result.index_price
        except ValidationError as exc:
            raise UpstreamError(
                "Deribit returned an invalid price response", retryable=False
            ) from exc
