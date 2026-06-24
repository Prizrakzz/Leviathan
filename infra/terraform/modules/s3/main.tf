resource "aws_s3_bucket" "data_lake" {
  bucket = var.bucket_name

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

data "aws_caller_identity" "current" {}

data "aws_iam_policy_document" "data_lake" {
  statement {
    sid    = "AllowS3InventoryDelivery"
    effect = "Allow"

    principals {
      type        = "Service"
      identifiers = ["s3.amazonaws.com"]
    }

    actions = ["s3:PutObject"]
    resources = [
      "${aws_s3_bucket.data_lake.arn}/metadata/s3_inventory/*",
    ]

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.current.account_id]
    }

    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = [aws_s3_bucket.data_lake.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id
  policy = data.aws_iam_policy_document.data_lake.json
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  versioning_configuration {
    status = "Suspended"
  }
}

resource "aws_s3_bucket_inventory" "weekly" {
  bucket = aws_s3_bucket.data_lake.id
  name   = "${var.project_name}-${var.environment}-weekly"

  included_object_versions = "Current"
  enabled                  = true
  optional_fields = [
    "Size",
    "LastModifiedDate",
    "ETag",
    "StorageClass",
    "ReplicationStatus",
    "EncryptionStatus",
  ]

  schedule {
    frequency = "Weekly"
  }

  destination {
    bucket {
      account_id = data.aws_caller_identity.current.account_id
      bucket_arn = aws_s3_bucket.data_lake.arn
      format     = "Parquet"
      prefix     = "metadata/s3_inventory"

      encryption {
        sse_s3 {}
      }
    }
  }

  depends_on = [aws_s3_bucket_policy.data_lake]
}

resource "aws_s3_bucket_server_side_encryption_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_lifecycle_configuration" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  rule {
    id     = "expire-temporary-multipart-uploads"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  rule {
    id     = "transition-old-raw-data"
    status = "Enabled"

    filter {
      prefix = "raw/"
    }

    transition {
      days          = 90
      storage_class = "STANDARD_IA"
    }
  }

  # Glue temp files and their noncurrent versions accumulate rapidly during
  # bulk job runs.  Expire everything after 1 day so versioning doesn't cause
  # cost spikes similar to the May 2026 incident ($13.44 S3 anomaly).
  rule {
    id     = "expire-glue-temp"
    status = "Enabled"

    filter {
      prefix = "glue-temp/"
    }

    expiration {
      days = 1
    }

    noncurrent_version_expiration {
      noncurrent_days = 1
    }
  }

  rule {
    id     = "expire-s3-inventory"
    status = "Enabled"

    filter {
      prefix = "metadata/s3_inventory/"
    }

    expiration {
      days = 90
    }
  }

  rule {
    id     = "manage-bronze-versions"
    status = "Enabled"

    filter {
      prefix = "bronze/"
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }

  rule {
    id     = "manage-silver-versions"
    status = "Enabled"

    filter {
      prefix = "silver/"
    }

    noncurrent_version_expiration {
      noncurrent_days = 7
    }

    transition {
      days          = 30
      storage_class = "STANDARD_IA"
    }
  }
}
