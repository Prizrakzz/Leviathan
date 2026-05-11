data "aws_iam_policy_document" "s3_data_lake_rw" {
  statement {
    sid = "ListDataLakeBucket"

    actions = [
      "s3:ListBucket"
    ]

    resources = [
      var.bucket_arn
    ]
  }

  statement {
    sid = "ReadWriteDataLakeObjects"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject"
    ]

    resources = [
      "${var.bucket_arn}/*"
    ]
  }
}

resource "aws_iam_policy" "s3_data_lake_rw" {
  name        = "${var.project_name}-${var.environment}-s3-data-lake-rw"
  description = "Read/write access to the Leviathan S3 data lake bucket."
  policy      = data.aws_iam_policy_document.s3_data_lake_rw.json
}