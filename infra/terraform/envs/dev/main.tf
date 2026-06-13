terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = var.aws_region
}

module "s3" {
  source = "../../modules/s3"

  bucket_name  = var.bucket_name
  project_name = var.project_name
  environment  = var.environment
}

module "iam" {
  source = "../../modules/iam"

  project_name               = var.project_name
  environment                = var.environment
  bucket_arn                 = module.s3.bucket_arn
  ecr_trainer_repository_arn = module.ecr_trainer.repository_arn
}

module "ecr" {
  source = "../../modules/ecr"

  project_name    = var.project_name
  environment     = var.environment
  repository_name = "leviathan-worker"
}

module "ecr_trainer" {
  source = "../../modules/ecr"

  project_name    = var.project_name
  environment     = var.environment
  repository_name = "leviathan-trainer"
}

module "batch" {
  source = "../../modules/batch"

  project_name    = var.project_name
  environment     = var.environment
  aws_region      = var.aws_region
  max_vcpus       = var.batch_max_vcpus
  subnet_ids      = var.batch_subnet_ids
  security_group_ids = var.batch_security_group_ids

  ecr_repository_url       = module.ecr.repository_url
  batch_execution_role_arn = module.iam.batch_execution_role_arn
  batch_job_role_arn       = module.iam.batch_job_role_arn
  leviathan_bucket         = var.bucket_name
}

module "glue" {
  source = "../../modules/glue"

  project_name      = var.project_name
  environment       = var.environment
  aws_region        = var.aws_region
  bucket_name       = var.bucket_name
  glue_job_role_arn = module.iam.glue_job_role_arn
}

module "cloudwatch" {
  source = "../../modules/cloudwatch"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
}

module "mlflow_server" {
  source = "../../modules/mlflow_server"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
  bucket_name  = var.bucket_name
  # Reuse the first Batch subnet — same VPC, same routing to S3 and SageMaker.
  subnet_id    = var.batch_subnet_ids[0]
}

# ---------------------------------------------------------------------------
# Monthly cost budget — alerts at 80 % actual and 100 % forecasted.
# Set budget_alert_email in terraform.tfvars to receive emails.
# ---------------------------------------------------------------------------
resource "aws_budgets_budget" "monthly_cost" {
  name         = "${var.project_name}-${var.environment}-monthly-budget"
  budget_type  = "COST"
  limit_amount = "30"
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  dynamic "notification" {
    for_each = var.budget_alert_email != "" ? [1] : []
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = 80
      threshold_type             = "PERCENTAGE"
      notification_type          = "ACTUAL"
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }

  dynamic "notification" {
    for_each = var.budget_alert_email != "" ? [1] : []
    content {
      comparison_operator        = "GREATER_THAN"
      threshold                  = 100
      threshold_type             = "PERCENTAGE"
      notification_type          = "FORECASTED"
      subscriber_email_addresses = [var.budget_alert_email]
    }
  }
}