# PostgreSQL 16 on RDS, single instance.
#
# The password is generated here and therefore exists in Terraform state. That
# is a considered trade-off, not an oversight: the state bucket is encrypted,
# versioned, private, and reachable only by the deploying IAM identity. The
# alternative — RDS-managed master passwords — rotates weekly by default,
# which would silently break the composed DATABASE_URL the application reads;
# password rotation belongs with a rotation-aware client, which is Phase 2
# work. Revisit when a Database Savings Plan conversation happens anyway.

resource "random_password" "master" {
  length = 32
  # URL-safe so the composed postgresql:// URL needs no percent-encoding, and
  # no character class the engine forbids ('/', '@', '"', spaces).
  special = false
}

resource "aws_db_subnet_group" "this" {
  name       = "auracles-${var.environment}"
  subnet_ids = var.private_subnet_ids

  tags = {
    Name = "auracles-${var.environment}"
  }
}

resource "aws_db_instance" "this" {
  identifier = "auracles-${var.environment}"

  engine         = "postgres"
  engine_version = "16"
  instance_class = var.instance_class

  db_name  = var.database_name
  username = var.master_username
  password = random_password.master.result
  port     = 5432

  allocated_storage     = var.allocated_storage_gb
  max_allocated_storage = var.allocated_storage_gb * 5
  storage_type          = "gp3"
  storage_encrypted     = true

  db_subnet_group_name   = aws_db_subnet_group.this.name
  vpc_security_group_ids = [var.security_group_id]
  # The subnet group has no internet route, but this flag is the belt to that
  # suspender: even a route-table mistake cannot expose the endpoint.
  publicly_accessible = false

  multi_az                  = var.multi_az
  backup_retention_period   = var.backup_retention_days
  deletion_protection       = var.deletion_protection
  skip_final_snapshot       = var.skip_final_snapshot
  final_snapshot_identifier = var.skip_final_snapshot ? null : "auracles-${var.environment}-final"

  # Patch releases apply in the maintenance window unattended; majors never do.
  auto_minor_version_upgrade = true
  apply_immediately          = var.environment != "production"

  performance_insights_enabled = false # not free below larger classes; revisit at scale

  tags = {
    Name = "auracles-${var.environment}"
  }
}
