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
        # SILVER-F085 RCA (2026-07-23, second occurrence of this class): the old rule-1
        # ("untagged after 1 day") broke the 14:00 UTC usda_esr run and left 16 jobdef
        # families' TOP revisions pinning DELETED digests. Mechanism: build_push_*.ps1
        # defaulted to a :latest-ONLY push, so the next push STOLE :latest and the prior
        # image -- still digest-pinned by ACTIVE Batch jobdefs -- became untagged and was
        # expired a day later. No grace period fixes that (a pinned-but-untagged digest
        # dies at ANY horizon), so the untagged rule is REMOVED: every push now carries a
        # durable datestamp tag (build scripts auto-derive one), and the only eviction is
        # the oldest-first count cap below. A-W7 Wave-3 RCA (2026-07-17, first occurrence):
        # the pre-30 hard cap (any, >5) evicted tagged digests during an 8-rebuild day and
        # broke 8 jobdefs the same way. Jobdefs/taskdefs pin digests for immutability; run
        # scripts/ops/check_ecr_pinned_digests.py before ANY lifecycle tightening.
        # D-PR-2: the cap is var.image_count_cap (worker 100, eda 60, everything else
        # the 30 default) and the description RENDERS it -- the live policies were
        # raised out of band on countNumber alone and have been describing themselves
        # as "Cap images at 30" while capping at 100/60 ever since.
        description = "Cap images at ${var.image_count_cap}, oldest first (digest pins must survive rebuild bursts; no untagged rule -- see RCA comment)"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.image_count_cap
        }
        action = {
          type = "expire"
        }
      }
    ]
  })
}
