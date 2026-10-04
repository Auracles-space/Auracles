# Inputs for the ECS module: cluster, IAM, log groups, task definitions, and
# the three services (api, worker, beat).

variable "environment" {
  description = "Environment name; prefixes resource names."
  type        = string
}

variable "aws_region" {
  description = "Region, for awslogs configuration."
  type        = string
}

variable "backend_image" {
  description = "Full image reference (repository URL + tag/digest) all three services run. One image, three commands — the deploy promotes a single artifact."
  type        = string
}

variable "public_subnet_ids" {
  description = "Where tasks launch (public IPs are their only outbound path — no NAT)."
  type        = list(string)
}

variable "api_security_group_id" {
  type        = string
  description = "SG for api tasks."
}

variable "worker_security_group_id" {
  type        = string
  description = "SG for worker tasks."
}

variable "beat_security_group_id" {
  type        = string
  description = "SG for beat tasks."
}

variable "target_group_arn" {
  description = "ALB target group the api service registers into."
  type        = string
}

variable "api_container_port" {
  description = "Port the api container listens on."
  type        = number
  default     = 8000
}

variable "environment_variables" {
  description = "Plain (non-secret) env vars shared by all three services. Per-service pool sizing is layered on top inside the module."
  type        = map(string)
}

variable "secret_arns" {
  description = "Secret env vars as name => Secrets Manager ARN. Injected by ECS at task start; values never appear in task definitions or state."
  type        = map(string)
}

variable "worker_use_spot" {
  description = "Run the worker on Fargate Spot (~70% off). Safe to reclaim: the Celery job it was running returns to the queue and reruns, because tasks are idempotent by project rule. The cost of a reclaim is the ~3 minute clamd/freshclam warmup before the replacement can scan anything."
  type        = bool
  default     = true
}

variable "beat_use_spot" {
  description = "Run beat on Fargate Spot. Separate from the worker because reclaiming beat is not the same bet: it is the only scheduler, and nothing queues a tick that never fired, so a reclaim silently skips whatever was due — a payout sweep, an escrow auto-release — until ECS replaces it. False in production (decision 2026-10-04); true in staging, where a missed window costs nothing."
  type        = bool
  default     = true
}

variable "log_retention_days" {
  description = "CloudWatch retention. The default of forever is a silent cost creeper; 30 days covers any realistic incident lookback at pilot scale."
  type        = number
  default     = 30
}

variable "s3_bucket_names" {
  description = "The four application bucket names, for the task role's S3 grant."
  type        = list(string)
}

variable "s3_delete_bucket_names" {
  description = "Buckets the task role may delete objects from: those the app erases from (GDPR erasure, artifact orphan sweep). A subset of s3_bucket_names."
  type        = list(string)
}

variable "clamav_image" {
  description = "ClamAV sidecar image for the worker task. Must carry linux/arm64 — the plain version tags (1.4) are amd64-only and the pull fails with 'manifest does not contain descriptor matching platform'; the -debian variants are the multi-arch ones."
  type        = string
  default     = "clamav/clamav:1.4-debian13-slim"
}
