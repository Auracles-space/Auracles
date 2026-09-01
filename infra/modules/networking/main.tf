# VPC, subnets, routing, and security groups for one environment.
#
# The design has no NAT gateway (a fixed ~$35/mo for a pilot that does not need
# it). That splits the subnets by a simple rule:
#
#   * ECS tasks live in PUBLIC subnets with public IPs — that is their only
#     path to the internet (Stripe, Paystack, Persona, Resend). Nothing can
#     reach them inbound: security groups admit only ALB→api on the app port.
#   * RDS and ElastiCache live in PRIVATE subnets with no internet route at
#     all. They need none, and this keeps both stores physically incapable of
#     answering the public internet regardless of any future SG mistake.
#
# Reaching the in-VPC stores from the tasks needs neither NAT nor IGW: private
# addresses inside the VPC CIDR match the VPC `local` route. (An earlier
# version of the infra doc claimed RDS/ElastiCache "force NAT" — wrong, and it
# distorted two vendor decisions before being caught.)

data "aws_availability_zones" "available" {
  state = "available"
}

locals {
  azs = slice(data.aws_availability_zones.available.names, 0, var.az_count)

  # Carve /20s (4k addresses each) from the VPC CIDR: public subnets first,
  # then private. Index math keeps the carving stable when az_count grows —
  # adding an AZ appends subnets rather than renumbering existing ones.
  public_cidrs  = [for i in range(var.az_count) : cidrsubnet(var.vpc_cidr, 4, i)]
  private_cidrs = [for i in range(var.az_count) : cidrsubnet(var.vpc_cidr, 4, i + 8)]
}

resource "aws_vpc" "this" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "auracles-${var.environment}"
  }
}

resource "aws_internet_gateway" "this" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "auracles-${var.environment}"
  }
}

resource "aws_subnet" "public" {
  count = var.az_count

  vpc_id            = aws_vpc.this.id
  cidr_block        = local.public_cidrs[count.index]
  availability_zone = local.azs[count.index]

  # Fargate tasks here receive public IPs at launch; with no NAT this is their
  # outbound path. Inbound is still closed by security groups.
  map_public_ip_on_launch = true

  tags = {
    Name = "auracles-${var.environment}-public-${local.azs[count.index]}"
    Tier = "public"
  }
}

resource "aws_subnet" "private" {
  count = var.az_count

  vpc_id            = aws_vpc.this.id
  cidr_block        = local.private_cidrs[count.index]
  availability_zone = local.azs[count.index]

  tags = {
    Name = "auracles-${var.environment}-private-${local.azs[count.index]}"
    Tier = "private"
  }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.this.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.this.id
  }

  tags = {
    Name = "auracles-${var.environment}-public"
  }
}

resource "aws_route_table_association" "public" {
  count = var.az_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

# Deliberately empty of internet routes: `local` only. RDS and ElastiCache can
# be reached from the tasks and can reach nothing outside the VPC.
resource "aws_route_table" "private" {
  vpc_id = aws_vpc.this.id

  tags = {
    Name = "auracles-${var.environment}-private"
  }
}

resource "aws_route_table_association" "private" {
  count = var.az_count

  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private.id
}

# Free, and keeps every byte of S3 traffic — artifact uploads, scans,
# thumbnails — inside AWS instead of round-tripping the public internet from a
# public IP. Attached to both route tables so a future move of tasks into
# private subnets keeps working unchanged.
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.this.id
  service_name      = "com.amazonaws.${data.aws_region.current.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids = [
    aws_route_table.public.id,
    aws_route_table.private.id,
  ]

  tags = {
    Name = "auracles-${var.environment}-s3"
  }
}

data "aws_region" "current" {}

# ---------------------------------------------------------------------------
# Security groups. Deny-by-default; every rule below is the complete inbound
# surface of the environment.
# ---------------------------------------------------------------------------

resource "aws_security_group" "alb" {
  name        = "auracles-${var.environment}-alb"
  description = "Public edge: HTTPS in from anywhere, HTTP only to redirect"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "HTTPS from the internet"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  ingress {
    description = "HTTP, answered only by a 301 to HTTPS at the listener"
    from_port   = 80
    to_port     = 80
    protocol    = "tcp"
    cidr_blocks = ["0.0.0.0/0"]
  }

  egress {
    description = "To the api tasks"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "auracles-${var.environment}-alb"
  }
}

resource "aws_security_group" "api_task" {
  name        = "auracles-${var.environment}-api-task"
  description = "api service: reachable only from the ALB, despite its public IP"
  vpc_id      = aws_vpc.this.id

  ingress {
    description     = "App port from the ALB only"
    from_port       = var.api_container_port
    to_port         = var.api_container_port
    protocol        = "tcp"
    security_groups = [aws_security_group.alb.id]
  }

  egress {
    description = "Outbound to providers, S3 endpoint, and in-VPC stores"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "auracles-${var.environment}-api-task"
  }
}

resource "aws_security_group" "worker_task" {
  name        = "auracles-${var.environment}-worker-task"
  description = "worker service: no inbound at all; clamd is a localhost sidecar"
  vpc_id      = aws_vpc.this.id

  egress {
    description = "Outbound to providers, S3 endpoint, and in-VPC stores"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "auracles-${var.environment}-worker-task"
  }
}

resource "aws_security_group" "beat_task" {
  name        = "auracles-${var.environment}-beat-task"
  description = "beat service: no inbound at all"
  vpc_id      = aws_vpc.this.id

  egress {
    description = "Outbound to providers and in-VPC stores"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "auracles-${var.environment}-beat-task"
  }
}

# Redis has no authentication worth the name; these SG rules ARE the access
# control. Source is the task security groups, never a CIDR — a CIDR rule
# would silently widen if the subnets ever changed.
resource "aws_security_group" "redis" {
  name        = "auracles-${var.environment}-redis"
  description = "ElastiCache: 6379 from the three task SGs only"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "Redis from api"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    security_groups = [
      aws_security_group.api_task.id,
    ]
  }

  ingress {
    description = "Redis from worker"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    security_groups = [
      aws_security_group.worker_task.id,
    ]
  }

  ingress {
    description = "Redis from beat"
    from_port   = 6379
    to_port     = 6379
    protocol    = "tcp"
    security_groups = [
      aws_security_group.beat_task.id,
    ]
  }

  egress {
    description = "None needed; kept explicit and empty of internet routes anyway"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = {
    Name = "auracles-${var.environment}-redis"
  }
}

resource "aws_security_group" "rds" {
  name        = "auracles-${var.environment}-rds"
  description = "RDS: 5432 from the three task SGs only"
  vpc_id      = aws_vpc.this.id

  ingress {
    description = "Postgres from api"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    security_groups = [
      aws_security_group.api_task.id,
    ]
  }

  ingress {
    description = "Postgres from worker"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    security_groups = [
      aws_security_group.worker_task.id,
    ]
  }

  ingress {
    description = "Postgres from beat"
    from_port   = 5432
    to_port     = 5432
    protocol    = "tcp"
    security_groups = [
      aws_security_group.beat_task.id,
    ]
  }

  egress {
    description = "None needed; kept explicit and bounded to the VPC"
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = [var.vpc_cidr]
  }

  tags = {
    Name = "auracles-${var.environment}-rds"
  }
}
