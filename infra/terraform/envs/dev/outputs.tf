output "bucket_name" {
  value = module.s3.bucket_name
}

output "bucket_arn" {
  value = module.s3.bucket_arn
}

output "s3_rw_policy_arn" {
  value = module.iam.s3_rw_policy_arn
}

