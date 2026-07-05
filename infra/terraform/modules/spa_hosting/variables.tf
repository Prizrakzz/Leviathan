variable "project_name" {
  type        = string
  description = "Project name."
}

variable "environment" {
  type        = string
  description = "Environment name."
}

variable "acm_certificate_arn" {
  type        = string
  description = "ACM cert ARN (us-east-1) covering the aliases. The Stage-2 wildcard cert."
}

variable "aliases" {
  type        = list(string)
  description = "CNAMEs the distribution serves (e.g. apex + www). Must be covered by the cert."
}

variable "tags" {
  type    = map(string)
  default = {}
}
