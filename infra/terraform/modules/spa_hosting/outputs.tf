output "bucket_name" {
  value       = aws_s3_bucket.spa.id
  description = "SPA origin bucket — deploy target for `aws s3 sync dist/`."
}

output "distribution_id" {
  value       = aws_cloudfront_distribution.spa.id
  description = "CloudFront distribution id — for cache invalidation after a deploy."
}

output "distribution_domain_name" {
  value       = aws_cloudfront_distribution.spa.domain_name
  description = "CloudFront *.cloudfront.net domain — ALIAS target for apex/www records."
}

output "distribution_hosted_zone_id" {
  value       = aws_cloudfront_distribution.spa.hosted_zone_id
  description = "CloudFront's fixed hosted-zone id (Z2FDTNDATAQYW2) for Route53 ALIAS records."
}
