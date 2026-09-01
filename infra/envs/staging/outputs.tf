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
