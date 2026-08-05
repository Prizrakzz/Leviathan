# ---------------------------------------------------------------------------
# SPA hosting for the Leviathan Terminal (Phase 4 Stage 3).
#
# Private S3 origin (NOT public) fronted by CloudFront via Origin Access Control (OAC, sigv4).
# This is a DEDICATED bucket — never the data-lake bucket (modules/s3), whose bucket policy a blanket
# apply would destroy. SPA client-side routing: 403/404 -> /index.html (200) so deep links resolve.
# ---------------------------------------------------------------------------

locals {
  name = "${var.project_name}-${var.environment}-terminal-spa"
}

resource "aws_s3_bucket" "spa" {
  bucket = local.name
  tags   = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })
}

# Private: no public access, ever. CloudFront reaches it via OAC only.
resource "aws_s3_bucket_public_access_block" "spa" {
  bucket                  = aws_s3_bucket.spa.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "spa" {
  bucket = aws_s3_bucket.spa.id
  rule { object_ownership = "BucketOwnerEnforced" }
}

resource "aws_cloudfront_origin_access_control" "spa" {
  name                              = "${local.name}-oac"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# D-TW-22: the app keeps OIDC ID tokens in localStorage; the page previously shipped with ZERO
# security headers. The AWS managed policy adds HSTS, X-Content-Type-Options, X-Frame-Options,
# Referrer-Policy and XSS-Protection. (A real CSP is a separate, deliberately-authored change --
# the managed policy carries none.)
data "aws_cloudfront_response_headers_policy" "security" {
  name = "Managed-SecurityHeadersPolicy"
}

resource "aws_cloudfront_distribution" "spa" {
  enabled             = true
  is_ipv6_enabled     = true
  default_root_object = "index.html"
  aliases             = var.aliases
  price_class         = "PriceClass_100" # NA + EU; cheapest tier for a research tool
  comment             = local.name

  origin {
    domain_name              = aws_s3_bucket.spa.bucket_regional_domain_name
    origin_id                = "spa-s3"
    origin_access_control_id = aws_cloudfront_origin_access_control.spa.id
  }

  default_cache_behavior {
    target_origin_id       = "spa-s3"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD", "OPTIONS"]
    cached_methods         = ["GET", "HEAD"]
    compress               = true
    # AWS managed CachingOptimized policy (hashed assets are immutable; index.html gets a no-cache header
    # at upload time so new deploys surface immediately).
    cache_policy_id            = "658327ea-f89d-4fab-a63d-7e88639e58f6"
    response_headers_policy_id = data.aws_cloudfront_response_headers_policy.security.id
  }

  # SPA deep links: S3 returns 403 (private) / 404 for unknown keys -> serve the app shell with 200.
  custom_error_response {
    error_code            = 403
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }
  custom_error_response {
    error_code            = 404
    response_code         = 200
    response_page_path    = "/index.html"
    error_caching_min_ttl = 0
  }

  viewer_certificate {
    acm_certificate_arn      = var.acm_certificate_arn
    ssl_support_method       = "sni-only"
    minimum_protocol_version = "TLSv1.2_2021"
  }

  restrictions {
    geo_restriction { restriction_type = "none" }
  }

  tags = merge(var.tags, { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" })
}

# Bucket policy: ONLY this CloudFront distribution (via OAC) may read objects.
data "aws_iam_policy_document" "spa" {
  statement {
    sid       = "AllowCloudFrontOAC"
    actions   = ["s3:GetObject"]
    resources = ["${aws_s3_bucket.spa.arn}/*"]
    principals {
      type        = "Service"
      identifiers = ["cloudfront.amazonaws.com"]
    }
    condition {
      test     = "StringEquals"
      variable = "AWS:SourceArn"
      values   = [aws_cloudfront_distribution.spa.arn]
    }
  }
}

resource "aws_s3_bucket_policy" "spa" {
  bucket = aws_s3_bucket.spa.id
  policy = data.aws_iam_policy_document.spa.json
}
