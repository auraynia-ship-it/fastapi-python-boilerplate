import logging
import json
import os
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


logger = logging.getLogger(__name__)
BLOB_API_URL = os.getenv("VERCEL_BLOB_API_URL", "https://vercel.com/api/blob")
BLOB_API_VERSION = os.getenv("VERCEL_BLOB_API_VERSION_OVERRIDE", "12")


@dataclass(frozen=True)
class BlobUploadResult:
    url: str
    pathname: str


def upload_bytes_to_vercel_blob(
    *,
    pathname: str,
    content: bytes,
    content_type: str,
    access: str = "public",
    token: str | None = None,
) -> BlobUploadResult:
    """
    Uploads bytes to Vercel Blob using its HTTP API.
    Requires `BLOB_READ_WRITE_TOKEN` in env or explicitly passed `token`.
    """
    token = (
        token
        or os.getenv("BLOB_READ_WRITE_TOKEN")
        or os.getenv("VERCEL_BLOB_READ_WRITE_TOKEN")
    )
    if not token:
        logger.warning("blob_upload_missing_token pathname=%s", pathname)
        raise RuntimeError("BLOB_READ_WRITE_TOKEN is not configured.")

    logger.info(
        "blob_upload_started pathname=%s content_type=%s access=%s size_bytes=%s",
        pathname,
        content_type,
        access,
        len(content),
    )
    blob = put_blob_via_http(
        pathname=pathname,
        content=content,
        content_type=content_type,
        access=access,
        token=token,
    )

    url = blob["url"]
    uploaded_pathname = blob["pathname"]
    logger.info("blob_upload_completed pathname=%s url=%s", uploaded_pathname, url)
    return BlobUploadResult(url=url, pathname=uploaded_pathname)


def put_blob_via_http(*, pathname, content, content_type, access, token):
    query = urlencode({"pathname": pathname})
    request = Request(
        f"{BLOB_API_URL}/?{query}",
        data=content,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/octet-stream",
            "x-api-version": BLOB_API_VERSION,
            "x-vercel-blob-access": access,
            "x-add-random-suffix": "1",
            "x-content-type": content_type,
            "x-content-length": str(len(content)),
        },
        method="PUT",
    )

    try:
        with urlopen(request, timeout=30) as response:
            response_data = json.loads(response.read().decode("utf-8"))
    except HTTPError as error:
        detail = error.read().decode("utf-8") if error.fp else error.reason
        logger.warning(
            "blob_upload_http_failed status_code=%s pathname=%s detail=%s",
            error.code,
            pathname,
            detail,
        )
        raise RuntimeError(f"Vercel Blob upload failed: {detail}") from error
    except (URLError, TimeoutError, json.JSONDecodeError) as error:
        logger.warning("blob_upload_http_error pathname=%s error=%s", pathname, error)
        raise RuntimeError(f"Unable to upload to Vercel Blob: {error}") from error

    if not response_data.get("url") or not response_data.get("pathname"):
        logger.warning(
            "blob_upload_http_invalid_response pathname=%s response=%s",
            pathname,
            response_data,
        )
        raise RuntimeError("Vercel Blob upload response did not include url/pathname.")

    return response_data
