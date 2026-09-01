# ElastiCache Redis: Celery broker + result backend + application cache.
#
# A replication group with one node rather than the simpler
# aws_elasticache_cluster, because only replication groups support encryption
# in transit — and this Redis carries refresh-token state and rate-limit
# counters, which should not cross even a private subnet in clear text. The
# application already speaks rediss:// (its URL builder passes ssl_cert_reqs),
# so TLS costs nothing in code.
#
# No AUTH token, deliberately: the security group is the access control (its
# rules admit only the three task SGs), an AUTH token would live in state and
# task env for marginal defense-in-depth, and Redis AUTH was never designed as
# a serious boundary. Revisit if the network topology ever loosens.

resource "aws_elasticache_subnet_group" "this" {
  name       = "auracles-${var.environment}"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name = "auracles-${var.environment}"
  }
}

resource "aws_elasticache_replication_group" "this" {
  replication_group_id = "auracles-${var.environment}"
  description          = "Celery broker + app cache for auracles-${var.environment}"

  engine         = "redis"
  engine_version = "7.1"
  node_type      = var.node_type

  num_cache_clusters         = 1
  automatic_failover_enabled = false # single node; failover needs >= 2 and is Phase 2

  subnet_group_name  = aws_elasticache_subnet_group.this.name
  security_group_ids = [var.security_group_id]

  transit_encryption_enabled = true
  at_rest_encryption_enabled = true

  # Celery queues are transient by design (tasks are idempotent and re-queued
  # on loss), so no snapshots: a restored broker replaying stale tasks is
  # worse than an empty one.
  snapshot_retention_limit = 0

  apply_immediately = var.environment != "production"

  tags = {
    Name = "auracles-${var.environment}"
  }
}
