# Everything the compute, database, and cache modules need to attach.

output "vpc_id" {
  description = "VPC id."
  value       = aws_vpc.this.id
}

output "public_subnet_ids" {
  description = "Public subnets — ECS tasks and the ALB."
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "Private subnets (no internet route) — RDS and ElastiCache subnet groups."
  value       = aws_subnet.private[*].id
}

output "alb_security_group_id" {
  description = "SG for the ALB."
  value       = aws_security_group.alb.id
}

output "api_task_security_group_id" {
  description = "SG for api tasks (ingress from ALB only)."
  value       = aws_security_group.api_task.id
}

output "worker_task_security_group_id" {
  description = "SG for worker tasks (no ingress)."
  value       = aws_security_group.worker_task.id
}

output "beat_task_security_group_id" {
  description = "SG for beat tasks (no ingress)."
  value       = aws_security_group.beat_task.id
}

output "redis_security_group_id" {
  description = "SG for ElastiCache (6379 from task SGs only)."
  value       = aws_security_group.redis.id
}

output "rds_security_group_id" {
  description = "SG for RDS (5432 from task SGs only)."
  value       = aws_security_group.rds.id
}
