# Staging outputs — grows with the stack.

output "vpc_id" {
  description = "Staging VPC."
  value       = module.networking.vpc_id
}

output "public_subnet_ids" {
  description = "Where ECS tasks and the ALB go."
  value       = module.networking.public_subnet_ids
}

output "private_subnet_ids" {
  description = "Where the RDS and ElastiCache subnet groups go."
  value       = module.networking.private_subnet_ids
}

output "rds_endpoint" {
  description = "Postgres host:port (private; reachable only from the task SGs)."
  value       = module.rds.endpoint
}

output "redis_endpoint" {
  description = "Redis primary (private; TLS only)."
  value       = module.redis.primary_endpoint
}

output "s3_buckets" {
  description = "The four application buckets, keyed by their S3_*_BUCKET env var meaning."
  value = {
    artifacts  = module.s3.artifacts_bucket
    avatars    = module.s3.avatars_bucket
    reports    = module.s3.reports_bucket
    thumbnails = module.s3.thumbnails_bucket
  }
}

output "database_url_secret_arn" {
  description = "Secrets Manager ARN the api/worker/beat task definitions reference for DATABASE_URL."
  value       = aws_secretsmanager_secret.database_url.arn
}

output "redis_url_secret_arn" {
  description = "Secrets Manager ARN for REDIS_URL."
  value       = aws_secretsmanager_secret.redis_url.arn
}
