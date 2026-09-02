# Cluster identity, for deploy tooling.

output "cluster_name" {
  description = "Cluster the deploy pipeline updates services in."
  value       = aws_ecs_cluster.this.name
}

output "service_names" {
  description = "The three service names."
  value = {
    api    = aws_ecs_service.api.name
    worker = aws_ecs_service.worker.name
    beat   = aws_ecs_service.beat.name
  }
}
