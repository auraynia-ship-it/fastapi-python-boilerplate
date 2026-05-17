import os
from dataclasses import dataclass


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
    Uploads bytes to Vercel Blob using the official `vercel` Python package.
    Requires `BLOB_READ_WRITE_TOKEN` in env or explicitly passed `token`.
    """
    token = token or os.getenv("BLOB_READ_WRITE_TOKEN")
    if not token:
        raise RuntimeError("BLOB_READ_WRITE_TOKEN is not configured.")

    try:
        from vercel.blob import BlobClient
    except ImportError as error:
        raise RuntimeError(
            "Vercel Blob Python SDK not installed. Install `vercel`."
        ) from error

    client = BlobClient(token=token)
    blob = client.put(
        pathname,
        content,
        access=access,
        add_random_suffix=True,
        content_type=content_type,
    )
    return BlobUploadResult(url=blob.url, pathname=blob.pathname)

