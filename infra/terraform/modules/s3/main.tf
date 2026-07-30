# The account id is needed by the inventory destination + its delivery policy (both re-declared at
# the foot of this file). Read from the caller rather than passed in, so the module stays
# self-contained for the two resources that need it.
data "aws_caller_identity" "current" {}

resource "aws_s3_bucket" "data_lake" {
  bucket = var.bucket_name

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_s3_bucket_versioning" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  versioning_configuration {
    status = "Suspended"
  }
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

  # RESTORED 2026-07-30 with the inventory itself: this rule is LIVE but had fallen out of config,
  # so re-declaring the inventory without it would leave a feed that writes weekly forever and
  # expires never. 90 days is the applied value.
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
# 6.5 click-to-page (P3-W4/B3): the SPA's pdf.js fetches presigned raw/ PDFs cross-origin (the presigned S3
# URL is a third origin vs the CloudFront SPA), and SOP requires Access-Control-Allow-Origin on the GET
# regardless of Range. GET/HEAD only — CORS grants no auth; access still requires the presigned signature.
resource "aws_s3_bucket_cors_configuration" "data_lake_pdf_cors" {
  bucket = aws_s3_bucket.data_lake.id

  cors_rule {
    allowed_headers = ["*"]
    allowed_methods = ["GET", "HEAD"]
    allowed_origins = [
      "https://leviathanconvexity.com",
      "https://www.leviathanconvexity.com",
      "http://localhost:5173",
    ]
    expose_headers  = ["Content-Length", "Content-Type", "Accept-Ranges", "Content-Range", "ETag"]
    max_age_seconds = 3600
  }
}

# ---------------------------------------------------------------------------
# RE-DECLARED 2026-07-30 (drift reconciliation). The weekly inventory and its delivery policy were
# created out of band and imported, but NEVER tracked in config -- `git log -S` finds no commit
# that ever added them. So terraform saw them as "in state, absent from configuration" and every
# plan proposed to DESTROY both, even though the feed is LIVE and producing (73+ manifest objects
# under metadata/s3_inventory/, weekly, through July). They are re-declared here from the live
# attributes rather than dropped: the feed is a cheap standing observability signal, and a destroy
# would have been an accident of omission rather than a decision.
#
# The two are ONE UNIT: the bucket policy's single statement is the delivery grant S3 Inventory
# itself needs to write into the prefix. Removing either one alone breaks the other.
# ---------------------------------------------------------------------------
resource "aws_s3_bucket_inventory" "weekly" {
  bucket = aws_s3_bucket.data_lake.id
  name   = "${var.project_name}-${var.environment}-weekly"

  included_object_versions = "Current"

  schedule {
    frequency = "Weekly"
  }

  optional_fields = [
    "ETag",
    "EncryptionStatus",
    "LastModifiedDate",
    "ReplicationStatus",
    "Size",
    "StorageClass",
  ]

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
}

resource "aws_s3_bucket_policy" "data_lake" {
  bucket = aws_s3_bucket.data_lake.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3InventoryDelivery"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "s3:PutObject"
      Resource  = "${aws_s3_bucket.data_lake.arn}/metadata/s3_inventory/*"
      Condition = {
        StringEquals = { "aws:SourceAccount" = data.aws_caller_identity.current.account_id }
        ArnLike      = { "aws:SourceArn" = aws_s3_bucket.data_lake.arn }
      }
    }]
  })
}
