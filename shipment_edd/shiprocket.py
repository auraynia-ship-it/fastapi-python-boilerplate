import json
from datetime import date, timedelta
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


SHIPROCKET_BASE_URL = "https://apiv2.shiprocket.in/v1/external"
SHIPROCKET_LOGIN_URL = f"{SHIPROCKET_BASE_URL}/auth/login"
SHIPROCKET_ORDERS_URL = f"{SHIPROCKET_BASE_URL}/orders"


class ShiprocketError(RuntimeError):
    pass


class ShiprocketClient:
    def __init__(self, token=None, email=None, password=None, timeout=30):
        self.token = token
        self.email = email
        self.password = password
        self.timeout = timeout

    def refresh_token(self):
        if not self.email or not self.password:
            raise ShiprocketError(
                "SHIPROCKET_EMAIL and SHIPROCKET_PASSWORD are required to refresh token."
            )

        response_data = self._request(
            SHIPROCKET_LOGIN_URL,
            method="POST",
            payload={"email": self.email, "password": self.password},
            include_auth=False,
            retry_on_unauthorized=False,
        )
        token = response_data.get("token")
        if not token:
            raise ShiprocketError("Shiprocket login response did not include a token.")

        self.token = token
        return token

    def fetch_orders(self, start_date=None, end_date=None, max_pages=20, per_page=100):
        orders = []
        start_date = start_date or (date.today() - timedelta(days=45))
        end_date = end_date or date.today()

        for page in range(1, max_pages + 1):
            params = {
                "page": page,
                "per_page": per_page,
                "from": start_date.isoformat(),
                "to": end_date.isoformat(),
            }
            response = self._request(f"{SHIPROCKET_ORDERS_URL}?{urlencode(params)}")
            page_orders = extract_orders(response)
            orders.extend(page_orders)

            if not page_orders or len(page_orders) < per_page:
                break

        return orders

    def _request(
        self,
        url,
        method="GET",
        payload=None,
        include_auth=True,
        retry_on_unauthorized=True,
    ):
        headers = {"Content-Type": "application/json"}
        body = None
        if include_auth:
            if not self.token:
                self.refresh_token()
            headers["Authorization"] = f"Bearer {self.token}"

        if payload is not None:
            body = json.dumps(payload).encode("utf-8")

        request = Request(url, data=body, headers=headers, method=method)
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 401 and include_auth and retry_on_unauthorized:
                self.refresh_token()
                return self._request(
                    url,
                    method=method,
                    payload=payload,
                    include_auth=include_auth,
                    retry_on_unauthorized=False,
                )

            detail = error.read().decode("utf-8") if error.fp else error.reason
            raise ShiprocketError(f"Shiprocket API error {error.code}: {detail}") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise ShiprocketError(f"Unable to call Shiprocket API: {error}") from error


def extract_orders(response):
    if isinstance(response, list):
        return response

    if not isinstance(response, dict):
        return []

    data = response.get("data")
    if isinstance(data, list):
        return data

    if isinstance(data, dict):
        for key in ("data", "orders", "results", "records"):
            value = data.get(key)
            if isinstance(value, list):
                return value

    for key in ("orders", "results", "records"):
        value = response.get(key)
        if isinstance(value, list):
            return value

    return []

