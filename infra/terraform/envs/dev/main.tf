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

  project_name = var.project_name
  environment  = var.environment
  bucket_arn   = module.s3.bucket_arn
}

module "ecr" {
  source = "../../modules/ecr"

  project_name    = var.project_name
  environment     = var.environment
  repository_name = "leviathan-worker"
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
  commodity         = var.commodity
}

module "cloudwatch" {
  source = "../../modules/cloudwatch"

  project_name = var.project_name
  environment  = var.environment
  aws_region   = var.aws_region
}