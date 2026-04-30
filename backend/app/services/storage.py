"""S3 storage service wrapping aioboto3.

One instance per process (constructed from settings at startup). All methods
are async. Uses `endpoint_url` override for LocalStack in dev.

Presigned POST URLs enforce content-length-range via policy conditions so the
server doesn't need to re-verify size.
"""

from typing import Any

import aioboto3
from botocore.exceptions import ClientError

from app.config import Settings, get_settings


# Map of common file extensions → MIME type for inline-preview defaults.
# Keep this minimal — only the artifact types the operator actually previews
# (PDFs, images). Anything else falls through to the S3-stored Content-Type
# (which is fine — non-previewable types just download, which is correct).
_EXT_TO_MIME: dict[str, str] = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".gif": "image/gif",
    ".webp": "image/webp",
    ".heic": "image/heic",
    ".html": "text/html",
    ".htm": "text/html",
    ".txt": "text/plain",
    ".csv": "text/csv",
    ".json": "application/json",
}


def _sniff_content_type(filename: str) -> str | None:
    """Best-effort MIME type from filename extension. ``None`` if unknown.

    Used by ``generate_presigned_download_url`` when the caller asks for an
    inline preview without supplying a ``content_type`` — Chrome's PDF /
    image inline renderer is gated on the response Content-Type, so an
    object that S3 stored as ``application/octet-stream`` (browser's
    fallback when MIME sniffing failed on upload) needs ``application/pdf``
    forced via ``ResponseContentType`` for the inline viewer to engage.
    """
    lower = filename.lower()
    for ext, mime in _EXT_TO_MIME.items():
        if lower.endswith(ext):
            return mime
    return None


class StorageService:
    def __init__(
        self,
        *,
        region: str,
        endpoint_url: str | None,
        access_key: str,
        secret_key: str,
        bucket: str,
        public_endpoint_url: str | None = None,
    ) -> None:
        self._session = aioboto3.Session(
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )
        self._endpoint_url = endpoint_url
        # Public URL used when presigning URLs that the browser will hit.
        # Falls back to the internal endpoint when not set (e.g. real AWS).
        self._public_endpoint_url = public_endpoint_url or endpoint_url
        self._bucket = bucket

    def _client(self):  # type: ignore[no-untyped-def]
        return self._session.client("s3", endpoint_url=self._endpoint_url)

    def _public_client(self):  # type: ignore[no-untyped-def]
        # Used ONLY to generate presigned URLs served to the browser.
        return self._session.client("s3", endpoint_url=self._public_endpoint_url)

    @property
    def bucket(self) -> str:
        return self._bucket

    async def ensure_bucket_exists(self) -> None:
        async with self._client() as s3:  # type: ignore[no-untyped-call]
            try:
                await s3.head_bucket(Bucket=self._bucket)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchBucket", "NotFound"):
                    kwargs: dict[str, object] = {"Bucket": self._bucket}
                    if self._session.region_name and self._session.region_name != "us-east-1":
                        kwargs["CreateBucketConfiguration"] = {
                            "LocationConstraint": self._session.region_name
                        }
                    await s3.create_bucket(**kwargs)
                else:
                    raise
            # Apply permissive CORS so browser-driven presigned POST uploads
            # work from the dev frontend (localhost:3000). In M8 AWS deploy,
            # replace with a tighter origin list.
            try:
                await s3.put_bucket_cors(
                    Bucket=self._bucket,
                    CORSConfiguration={
                        "CORSRules": [
                            {
                                "AllowedMethods": ["GET", "PUT", "POST", "HEAD"],
                                "AllowedOrigins": ["*"],
                                "AllowedHeaders": ["*"],
                                "ExposeHeaders": ["ETag", "x-amz-request-id"],
                                "MaxAgeSeconds": 3000,
                            }
                        ]
                    },
                )
            except ClientError:
                # Non-fatal: real AWS may refuse and that's fine — we only
                # need this for LocalStack dev.
                pass

    async def upload_object(self, key: str, body: bytes, content_type: str | None = None) -> None:
        async with self._client() as s3:  # type: ignore[no-untyped-call]
            kwargs: dict[str, object] = {"Bucket": self._bucket, "Key": key, "Body": body}
            if content_type:
                kwargs["ContentType"] = content_type
            await s3.put_object(**kwargs)

    async def download_object(self, key: str) -> bytes:
        async with self._client() as s3:  # type: ignore[no-untyped-call]
            resp = await s3.get_object(Bucket=self._bucket, Key=key)
            return await resp["Body"].read()  # type: ignore[no-any-return]

    async def delete_object(self, key: str) -> None:
        async with self._client() as s3:  # type: ignore[no-untyped-call]
            await s3.delete_object(Bucket=self._bucket, Key=key)

    async def copy_object(self, source_key: str, dest_key: str) -> None:
        async with self._client() as s3:  # type: ignore[no-untyped-call]
            await s3.copy_object(
                Bucket=self._bucket,
                Key=dest_key,
                CopySource={"Bucket": self._bucket, "Key": source_key},
            )

    async def object_exists(self, key: str) -> bool:
        async with self._client() as s3:  # type: ignore[no-untyped-call]
            try:
                await s3.head_object(Bucket=self._bucket, Key=key)
                return True
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchKey", "NotFound"):
                    return False
                raise

    async def get_object_metadata(self, key: str) -> dict[str, object] | None:
        async with self._client() as s3:  # type: ignore[no-untyped-call]
            try:
                resp = await s3.head_object(Bucket=self._bucket, Key=key)
            except ClientError as e:
                code = e.response.get("Error", {}).get("Code")
                if code in ("404", "NoSuchKey", "NotFound"):
                    return None
                raise
            return {
                "size_bytes": resp.get("ContentLength"),
                "content_type": resp.get("ContentType"),
                "etag": resp.get("ETag"),
            }

    async def generate_presigned_download_url(
        self,
        key: str,
        expires_in: int = 900,
        *,
        disposition: str = "inline",
        filename: str | None = None,
        content_type: str | None = None,
    ) -> str:
        """Return a presigned GET URL.

        ``disposition`` controls how the browser treats the response:

          * ``"inline"`` (default) — render images inline, open PDFs in the
            viewer. Used by every "View source" / preview surface. Without
            this override the browser honours whatever Content-Disposition
            was stored on the S3 object at upload time, which in dev has
            sometimes been ``attachment`` — triggering an unwanted download
            every time the artefact is opened.
          * ``"attachment"`` — forces a download dialog. Used only for the
            explicit "Download" button.

        ``content_type`` overrides the response Content-Type header. We need
        this on top of disposition because Chrome's PDF / image inline
        renderer is gated on Content-Type: artefacts uploaded with
        ``application/octet-stream`` (the browser's fallback when MIME
        sniffing fails on upload) get pushed to the Save dialog regardless
        of ``Content-Disposition: inline``. When the caller doesn't pass an
        explicit type and ``filename`` is given, we sniff a default from the
        extension (``.pdf`` → ``application/pdf``, ``.jpg`` → ``image/jpeg``,
        etc.) so previews "just work" without every call site having to
        plumb the MIME type through.
        """
        disp_value = disposition.lower()
        if disp_value not in ("inline", "attachment"):
            disp_value = "inline"
        if filename:
            # Quote-and-escape so weird filenames don't break the header.
            safe_name = filename.replace('"', '').replace("\\", "")
            disp_header = f'{disp_value}; filename="{safe_name}"'
        else:
            disp_header = disp_value

        # Sniff Content-Type from the filename extension when the caller did
        # not pass one explicitly. Only applied for inline (preview) — the
        # download path doesn't care what type the browser thinks it is.
        effective_ct = content_type
        if effective_ct is None and disp_value == "inline" and filename:
            effective_ct = _sniff_content_type(filename)

        params: dict[str, Any] = {
            "Bucket": self._bucket,
            "Key": key,
            "ResponseContentDisposition": disp_header,
        }
        if effective_ct:
            params["ResponseContentType"] = effective_ct

        async with self._public_client() as s3:  # type: ignore[no-untyped-call]
            return await s3.generate_presigned_url(  # type: ignore[no-any-return]
                "get_object",
                Params=params,
                ExpiresIn=expires_in,
            )

    async def generate_presigned_upload_url(
        self,
        key: str,
        *,
        expires_in: int = 900,
        max_size_bytes: int = 100 * 1024 * 1024,
        content_type: str | None = None,
    ) -> dict[str, object]:
        """Returns a presigned POST with size cap enforced by S3 policy.

        Client sends multipart POST to `url` with `fields` + file.
        Returns {"url", "fields", "key"}.
        """
        conditions: list[object] = [["content-length-range", 0, max_size_bytes]]
        fields: dict[str, str] = {}
        if content_type:
            conditions.append({"Content-Type": content_type})
            fields["Content-Type"] = content_type

        async with self._public_client() as s3:  # type: ignore[no-untyped-call]
            resp = await s3.generate_presigned_post(
                Bucket=self._bucket,
                Key=key,
                Fields=fields,
                Conditions=conditions,
                ExpiresIn=expires_in,
            )
        return {"url": resp["url"], "fields": resp["fields"], "key": key}


_instance: StorageService | None = None


def get_storage(settings: Settings | None = None) -> StorageService:
    """FastAPI dependency helper. One instance per process."""
    global _instance
    if _instance is None:
        s = settings or get_settings()
        _instance = StorageService(
            region=s.aws_region,
            endpoint_url=s.aws_s3_endpoint_url,
            public_endpoint_url=s.aws_s3_public_endpoint_url,
            access_key=s.aws_access_key_id,
            secret_key=s.aws_secret_access_key,
            bucket=s.s3_bucket,
        )
    return _instance


def reset_storage_for_tests() -> None:
    """Tests use their own StorageService; call this to clear the singleton."""
    global _instance
    _instance = None
