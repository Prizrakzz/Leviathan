"""Shared in-memory AWS fakes for the SILVER-F012/F013/F015 publisher-family tests.

These fakes never touch botocore's wire, so the F002 default-deny network guard never fires and the
tests are fully hermetic. They model exactly the conditional-write / not-found / already-exists error
shapes the publisher family branches on -- using real ``botocore.exceptions.ClientError`` so the
production error-code extraction paths are exercised (never the prod bucket/db names).
"""
from __future__ import annotations

import hashlib
import io
from typing import Optional

import pytest
from botocore.exceptions import ClientError

TEST_BUCKET = "leviathan-test"           # allowlisted test surface; NEVER the prod bucket
TEST_DB = "leviathan_test"               # allowlisted test database


def _client_error(code: str, op: str) -> ClientError:
    return ClientError({"Error": {"Code": code, "Message": code}}, op)


class _Body:
    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    def read(self, *a, **k) -> bytes:
        return self._buf.read(*a, **k)


class FakeS3:
    """In-memory S3 with conditional-write (IfNoneMatch/IfMatch), Range GET, HEAD, copy, delete."""

    def __init__(self):
        self.store: dict[tuple[str, str], bytes] = {}

    @staticmethod
    def _etag(body: bytes) -> str:
        return hashlib.md5(body).hexdigest()

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None, **kw):
        exists = (Bucket, Key) in self.store
        if IfNoneMatch == "*" and exists:
            raise _client_error("PreconditionFailed", "PutObject")
        if IfMatch is not None:
            if not exists or self._etag(self.store[(Bucket, Key)]) != IfMatch:
                raise _client_error("PreconditionFailed", "PutObject")
        body = Body if isinstance(Body, (bytes, bytearray)) else bytes(Body, "utf-8")
        self.store[(Bucket, Key)] = bytes(body)
        return {"ETag": f'"{self._etag(bytes(body))}"'}

    def get_object(self, Bucket, Key, Range: Optional[str] = None, **kw):
        if (Bucket, Key) not in self.store:
            raise _client_error("NoSuchKey", "GetObject")
        data = self.store[(Bucket, Key)]
        if Range:
            # "bytes=0-3" inclusive
            _, rng = Range.split("=", 1)
            lo, hi = rng.split("-")
            data = data[int(lo):int(hi) + 1]
        return {"Body": _Body(data), "ETag": f'"{self._etag(self.store[(Bucket, Key)])}"',
                "ContentLength": len(self.store[(Bucket, Key)])}

    def head_object(self, Bucket, Key, **kw):
        if (Bucket, Key) not in self.store:
            raise _client_error("404", "HeadObject")
        return {"ContentLength": len(self.store[(Bucket, Key)])}

    def delete_object(self, Bucket, Key, **kw):
        self.store.pop((Bucket, Key), None)
        return {}

    def copy_object(self, Bucket, Key, CopySource, **kw):
        src = (CopySource["Bucket"], CopySource["Key"])
        if src not in self.store:
            raise _client_error("NoSuchKey", "CopyObject")
        self.store[(Bucket, Key)] = self.store[src]
        return {}

    def keys(self):
        return sorted(k for _, k in self.store)


class FakeGlue:
    """In-memory Glue catalog: tables + registered partitions, with EntityNotFound/AlreadyExists."""

    def __init__(self):
        self.tables: dict[str, dict] = {}
        self.partitions: dict[tuple[str, tuple], dict] = {}
        self.calls: list[tuple] = []

    # tables
    def get_table(self, DatabaseName, Name, **kw):
        self.calls.append(("get_table", Name))
        if Name not in self.tables:
            raise _client_error("EntityNotFoundException", "GetTable")
        return {"Table": self.tables[Name]}

    def create_table(self, DatabaseName, TableInput, **kw):
        self.calls.append(("create_table", TableInput["Name"]))
        if TableInput["Name"] in self.tables:
            raise _client_error("AlreadyExistsException", "CreateTable")
        self.tables[TableInput["Name"]] = dict(TableInput)
        return {}

    def update_table(self, DatabaseName, TableInput, **kw):
        self.calls.append(("update_table", TableInput["Name"]))
        if TableInput["Name"] not in self.tables:
            raise _client_error("EntityNotFoundException", "UpdateTable")
        self.tables[TableInput["Name"]] = dict(TableInput)
        return {}

    # partitions
    def get_partition(self, DatabaseName, TableName, PartitionValues, **kw):
        key = (TableName, tuple(str(v) for v in PartitionValues))
        if key not in self.partitions:
            raise _client_error("EntityNotFoundException", "GetPartition")
        return {"Partition": self.partitions[key]}

    def create_partition(self, DatabaseName, TableName, PartitionInput, **kw):
        self.calls.append(("create_partition", TableName, tuple(PartitionInput["Values"])))
        key = (TableName, tuple(str(v) for v in PartitionInput["Values"]))
        if key in self.partitions:
            raise _client_error("AlreadyExistsException", "CreatePartition")
        self.partitions[key] = dict(PartitionInput)
        return {}

    def update_partition(self, DatabaseName, TableName, PartitionValueList, PartitionInput, **kw):
        self.calls.append(("update_partition", TableName, tuple(PartitionValueList)))
        key = (TableName, tuple(str(v) for v in PartitionValueList))
        if key not in self.partitions:
            raise _client_error("EntityNotFoundException", "UpdatePartition")
        self.partitions[key] = dict(PartitionInput)
        return {}


@pytest.fixture()
def fake_s3() -> FakeS3:
    return FakeS3()


@pytest.fixture()
def fake_glue() -> FakeGlue:
    return FakeGlue()


def canonical_authorization():
    """A canonical (may_mutate_canonical=True) Authorization without going through the guard env
    checks -- used to drive the mutate path in the fakes. The DENIED end-to-end path is tested
    separately through authorize_publish itself."""
    from leviathan.common.publish_guard import Authorization, PublishMode
    return Authorization(mode=PublishMode.CANONICAL, may_mutate_canonical=True, readiness=False,
                         reason="test canonical")


def dryrun_authorization():
    from leviathan.common.publish_guard import Authorization, PublishMode
    return Authorization(mode=PublishMode.DRY_RUN, may_mutate_canonical=False, readiness=False,
                         reason="test dry-run")


def shadow_authorization():
    from leviathan.common.publish_guard import Authorization, PublishMode
    return Authorization(mode=PublishMode.SHADOW, may_mutate_canonical=False, readiness=False,
                         reason="test shadow")
