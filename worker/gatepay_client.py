"""HTTP client tipis untuk GatePay (https://gatepay.biz.id/docs).

Auth pakai header `x-api-key`. Semua request via httpx.AsyncClient.
"""

from __future__ import annotations

import httpx

GATEPAY_BASE_URL = "https://gatepay.biz.id"


class GatePayError(Exception):
    def __init__(self, message: str, status: int = 0, body: str = ""):
        super().__init__(message)
        self.status = status
        self.body = body


def _headers(api_key: str) -> dict:
    return {
        "x-api-key": api_key,
        "content-type": "application/json",
        "accept": "application/json",
    }


async def _request(method: str, api_key: str, path: str, json: dict | None = None) -> dict:
    if not api_key:
        raise GatePayError("GatePay API key belum diatur untuk akun ini")
    url = f"{GATEPAY_BASE_URL}{path}"
    async with httpx.AsyncClient(timeout=20.0) as http:
        resp = await http.request(method, url, headers=_headers(api_key), json=json)
    if resp.status_code >= 400:
        raise GatePayError(
            f"GatePay {resp.status_code}: {resp.text[:200]}",
            status=resp.status_code,
            body=resp.text,
        )
    try:
        return resp.json()
    except Exception:
        raise GatePayError(f"Response bukan JSON: {resp.text[:200]}", status=resp.status_code)


async def create_order(
    api_key: str,
    base_amount: int,
    reference: str | None = None,
    expires_in: int | None = None,
) -> dict:
    """POST /api/orders → dapat {id, status, unique_amount, qris, checkout_url, ...}."""
    body: dict = {"base_amount": int(base_amount)}
    if reference:
        body["reference"] = reference
    if expires_in:
        # GatePay docs: field masa berlaku order adalah `ttl_seconds`.
        body["ttl_seconds"] = int(expires_in)
    return await _request("POST", api_key, "/api/orders", json=body)


async def get_order(api_key: str, order_id: str) -> dict:
    return await _request("GET", api_key, f"/api/orders/{order_id}")


async def cancel_order(api_key: str, order_id: str) -> dict:
    return await _request("POST", api_key, f"/api/orders/{order_id}/cancel")


async def test_connection(api_key: str) -> dict:
    """Tes ringan: bikin order 1000 lalu langsung cancel supaya tidak ninggalin pending."""
    order = await create_order(api_key, 1000, reference="lovable_test_connection")
    order_id = order.get("id")
    if order_id:
        try:
            await cancel_order(api_key, order_id)
        except Exception:
            pass
    return {"ok": True, "sample_order_id": order_id}
