# The four application buckets: artifacts, avatars, reports, thumbnails.
#
# All four are private with every public-access switch blocked. Nothing ever
# reads them anonymously: delivery is presigned URLs minted after a license
# check (CLAUDE.md security rule), and the browser talks to S3 directly with
# CORS scoped to the frontend origin.
#
# One aws_s3_bucket resource with for_each rather than four copies — the
# settings are identical by policy, and a per-bucket drift (say, versioning
# quietly off on one) is exactly the kind of mistake four copies invite.

locals {
  # Suffix layout: auracles-<purpose>-<environment>-<account>. The account id
  # makes names globally unique; the environment keeps staging and production
  # buckets coexisting.
  buckets = {
    artifacts  = "auracles-artifacts-${var.environment}-${var.account_id}"
    avatars    = "auracles-avatars-${var.environment}-${var.account_id}"
    reports    = "auracles-reports-${var.environment}-${var.account_id}"
    thumbnails = "auracles-thumbnails-${var.environment}-${var.account_id}"
  }

  # Buckets the browser touches directly via presigned URLs. Reports are
  # generated and served backend-side; thumbnails are read through presigned
  # GETs but never written from the browser.
  cors_buckets = ["artifacts", "avatars"]
}

resource "aws_s3_bucket" "this" {
  for_each = local.buckets

  bucket        = each.value
  force_destroy = var.force_destroy

  tags = {
    Name    = each.value
    Purpose = each.key
  }
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.this

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

# Versioning on artifacts only: they are user-owned IP and the subject of
# money disputes, so an overwritten or deleted artifact must be recoverable.
# Avatars/thumbnails are re-uploadable, reports re-generatable.
resource "aws_s3_bucket_versioning" "artifacts" {
  bucket = aws_s3_bucket.this["artifacts"].id

  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_cors_configuration" "this" {
  for_each = toset(local.cors_buckets)

  bucket = aws_s3_bucket.this[each.key].id

  cors_rule {
    allowed_origins = var.cors_allowed_origins
    # POST is the one that matters: every browser upload in the app goes through
    # a presigned *POST* policy (generate_presigned_post), not a presigned PUT.
    # Without it the browser's preflight fails and the upload dies as an opaque
    # network error — artifacts, avatars, org logos, deliverables and KYC
    # documents alike. PUT stays for any direct-PUT path and costs nothing.
    allowed_methods = ["GET", "POST", "PUT", "HEAD"]
    allowed_headers = ["*"]
    expose_headers  = ["ETag"]
    max_age_seconds = 3600
  }
}

# Multipart uploads that never complete hold invisible storage forever.
resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    id     = "abort-incomplete-multipart"
    status = "Enabled"

    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
