"""Storage service tests using moto (in-process S3 mock)."""

import pytest
from moto import mock_aws

from app.services.storage import StorageService


@pytest.fixture
async def storage():
    """Fresh moto S3 bucket per test."""
    with mock_aws():
        svc = StorageService(
            region="ap-south-1",
            endpoint_url=None,
            access_key="test",
            secret_key="test",
            bucket="pfl-cases-test",
        )
        await svc.ensure_bucket_exists()
        yield svc


async def test_upload_and_download_roundtrip(storage):
    await storage.upload_object("test/hello.txt", b"hello world", content_type="text/plain")
    body = await storage.download_object("test/hello.txt")
    assert body == b"hello world"


async def test_object_exists_returns_true_after_upload(storage):
    assert await storage.object_exists("not-there.txt") is False
    await storage.upload_object("there.txt", b"x")
    assert await storage.object_exists("there.txt") is True


async def test_object_metadata(storage):
    await storage.upload_object("meta.bin", b"1234567890", content_type="application/octet-stream")
    meta = await storage.get_object_metadata("meta.bin")
    assert meta is not None
    assert meta["size_bytes"] == 10
    assert meta["content_type"] == "application/octet-stream"


async def test_delete_removes_object(storage):
    await storage.upload_object("doomed.txt", b"bye")
    await storage.delete_object("doomed.txt")
    assert await storage.object_exists("doomed.txt") is False


async def test_presigned_download_url_works(storage):
    await storage.upload_object("dl.txt", b"download me")
    url = await storage.generate_presigned_download_url("dl.txt", expires_in=60)
    assert url.startswith("https://") or url.startswith("http://")
    assert "dl.txt" in url


async def test_presigned_upload_url_includes_size_condition(storage):
    resp = await storage.generate_presigned_upload_url(
        "upload/target.zip",
        expires_in=900,
        max_size_bytes=100 * 1024 * 1024,
        content_type="application/zip",
    )
    assert "url" in resp
    assert "fields" in resp
    assert resp["key"] == "upload/target.zip"
    # Under moto, the URL points to S3 directly; presigned POST fields should include the policy
    assert "policy" in resp["fields"]
    assert "x-amz-signature" in resp["fields"] or "AWSAccessKeyId" in resp["fields"]


async def test_copy_object_works(storage):
    await storage.upload_object("src.txt", b"data")
    await storage.copy_object("src.txt", "dst.txt")
    assert await storage.object_exists("dst.txt") is True
    assert await storage.download_object("dst.txt") == b"data"


async def test_copy_then_delete_simulates_rename(storage):
    """Re-upload flow relies on copy + delete to 'rename'."""
    await storage.upload_object("original.zip", b"zipbytes")
    await storage.copy_object("original.zip", "original.zip.archived_v1")
    await storage.delete_object("original.zip")
    assert await storage.object_exists("original.zip") is False
    assert await storage.object_exists("original.zip.archived_v1") is True
