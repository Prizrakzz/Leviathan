output "bucket_name" {
  value = aws_s3_bucket.data_lake.bucket
}

output "bucket_arn" {
  value = aws_s3_bucket.data_lake.arn
}

output "inventory_configuration_name" {
  value = aws_s3_bucket_inventory.weekly.name
}
