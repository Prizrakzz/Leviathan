variable "project_name" {
  type        = string
  description = "Project name."
}

variable "environment" {
  type        = string
  description = "Environment name."
}

variable "vpc_id" {
  type        = string
  description = "VPC the ALB + target group live in (same VPC as the Fargate tasks + RDS)."
}

variable "subnet_ids" {
  type        = list(string)
  description = "Public subnet IDs for the internet-facing ALB (>= 2 AZs). Reuses the Batch subnets."
}

variable "admin_cidrs" {
  type        = list(string)
  description = <<-EOT
    CIDRs allowed inbound to the ALB. Stage 1 (private validation) locks this to your IP
    (e.g. ["203.0.113.4/32"]). Stage 4 opens it to 0.0.0.0/0 once Cognito + HTTPS front it.
  EOT
}

variable "container_port" {
  type        = number
  description = "Port the serving container listens on (uvicorn)."
  default     = 8080
}

variable "health_check_path" {
  type        = string
  description = "ALB target-group health check path."
  default     = "/healthz"
}

variable "idle_timeout" {
  type        = number
  description = "ALB idle timeout (s). SSE turns run 30-90s; keep well above that."
  default     = 1800
}

variable "listener_port" {
  type        = number
  description = "ALB listener port. Stage 1 = 80 (HTTP, IP-locked). Stage 4 swaps to 443 + ACM."
  default     = 80
}

variable "enable_https" {
  type        = bool
  description = <<-EOT
    Stage 2: add an HTTPS:443 listener (using certificate_arn) and turn the :80 listener into a
    301 redirect to 443. When false the module stays Stage-1 (plain HTTP:80 forward). SG opens 443
    to admin_cidrs when true (still IP-locked until Stage 5 flips public_ingress).
  EOT
  default     = false
}

variable "certificate_arn" {
  type        = string
  description = "ACM certificate ARN (us-east-1) for the 443 listener. Required when enable_https = true."
  default     = ""
}

variable "public_ingress" {
  type        = bool
  description = <<-EOT
    Stage 5 kill-switch. false (default) = ALB inbound locked to admin_cidrs. true = 443 (and the :80
    redirect) open to 0.0.0.0/0. Flip to false to instantly re-lock. Only flip true AFTER auth is verified
    returning 401 to tokenless requests.
  EOT
  default     = false
}

variable "tags" {
  type    = map(string)
  default = {}
}
