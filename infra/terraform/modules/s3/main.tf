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
