import json
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SupabaseError(RuntimeError):
    pass


class SupabaseRestClient:
    def __init__(self, url, key, timeout=30):
        self.url = (url or "").rstrip("/")
        self.key = key
        self.timeout = timeout

    @property
    def enabled(self):
        return bool(self.url and self.key)

    def insert(self, table, rows, returning="representation"):
        return self._write(table, rows, returning=returning)

    def upsert(self, table, rows, on_conflict, returning="representation"):
        query = urlencode({"on_conflict": on_conflict})
        return self._write(
            table,
            rows,
            query=query,
            prefer=f"resolution=merge-duplicates,return={returning}",
        )

    def table_exists(self, table):
        if not self.enabled:
            return False, "Supabase URL/key are not configured."

        query = urlencode({"select": "*", "limit": 1})
        request = Request(
            f"{self.url}/rest/v1/{table}?{query}",
            headers={
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
            },
            method="GET",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                response.read()
            return True, None
        except HTTPError as error:
            detail = error.read().decode("utf-8") if error.fp else error.reason
            return False, f"Supabase API error {error.code}: {detail}"
        except (URLError, TimeoutError) as error:
            return False, f"Unable to reach Supabase REST API: {error}"

    def _write(self, table, rows, query="", prefer="return=representation", returning=None):
        if not self.enabled:
            return []

        if returning is not None:
            prefer = f"return={returning}"

        url = f"{self.url}/rest/v1/{table}"
        if query:
            url = f"{url}?{query}"

        payload = rows if isinstance(rows, list) else [rows]
        request = Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "apikey": self.key,
                "Authorization": f"Bearer {self.key}",
                "Prefer": prefer,
            },
            method="POST",
        )

        try:
            with urlopen(request, timeout=self.timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else []
        except HTTPError as error:
            detail = error.read().decode("utf-8") if error.fp else error.reason
            raise SupabaseError(f"Supabase API error {error.code}: {detail}") from error
        except (URLError, TimeoutError, json.JSONDecodeError) as error:
            raise SupabaseError(f"Unable to call Supabase REST API: {error}") from error
