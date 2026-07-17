resource "aws_ecr_repository" "this" {
  name                 = "${var.project_name}-${var.environment}-${var.repository_name}"
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  tags = {
    Project     = var.project_name
    Environment = var.environment
    ManagedBy   = "terraform"
  }
}

resource "aws_ecr_lifecycle_policy" "this" {
  repository = aws_ecr_repository.this.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Expire untagged images after 1 day (orphans left when :latest is re-pushed)"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = {
          type = "expire"
        }
      },
      {
        rulePriority = 2
        # A-W7 Wave-3 RCA: the old hard cap (any, >5) EXPIRED TAGGED images during rapid
        # rebuild days -- 8 worker rebuilds on 2026-07-17 evicted every pre-w4 digest and
        # broke 8 ACTIVE Batch jobdefs that pinned them (CannotPullContainerError at the
        # esr/wasde canaries). Jobdefs pin digests for immutability; the registry must
        # therefore retain tagged images far beyond the rebuild cadence. 30 tagged images
        # at ~1-2GB each is a few $/mo -- cheap vs a broken scheduled pipeline.
        description  = "Cap tagged images at 30 (digest pins must survive rebuild bursts)"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = 30
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
