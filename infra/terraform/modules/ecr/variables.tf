variable "project_name" {
  type        = string
  description = "Project name."
}

variable "environment" {
  type        = string
  description = "Environment name."
}

variable "repository_name" {
  type        = string
  description = "Short repository name. Will be prefixed with project_name and environment."
}

variable "image_count_cap" {
  # The rule-1 `imageCountMoreThan` ceiling -- the ONLY eviction this module performs
  # (see the RCA comment in main.tf: there is deliberately no untagged rule).
  #
  # D-PR-2 (2026-08-04): the worker repo was raised to 100 and the eda repo to 60
  # OUT OF BAND, by a console/CLI read-modify-write against the live policy, because
  # the module's hardcoded 30 was evicting digests that ACTIVE Batch job definitions
  # still pinned. That raise was invisible to terraform, so every subsequent plan
  # carried a silent `countNumber 100 -> 30` revert. Parameterizing it is what makes
  # the live cap a fact of the repo instead of a fact of somebody's shell history.
  #
  # The DESCRIPTION is interpolated from this same variable on purpose: the
  # out-of-band edit only moved countNumber, so the live policies still describe
  # themselves as "Cap images at 30" while capping at 100/60. A cap that lies about
  # its own size is how the next reader mis-plans the next tightening.
  #
  # Raise this, never lower it blind: run scripts/ops/check_ecr_pinned_digests.py
  # first and read how many images the repo holds against how many digests ACTIVE
  # jobdefs/taskdefs pin.
  type        = number
  description = "Rule-1 imageCountMoreThan ceiling for this repository. Oldest images beyond the cap expire. Also rendered into the rule description so the policy cannot misdescribe its own size."
  default     = 30

  validation {
    condition     = var.image_count_cap >= 30
    error_message = "image_count_cap must be >= 30. Both ECR eviction incidents (A-W7 Wave-3 2026-07-17 at cap 5, SILVER-F085 2026-07-23) were caused by a cap below the burst rebuild rate breaking digest-pinned jobdefs; lowering below 30 requires scripts/ops/check_ecr_pinned_digests.py evidence and a deliberate change to this floor."
  }
}
