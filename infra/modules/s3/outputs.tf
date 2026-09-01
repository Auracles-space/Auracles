# Bucket names, matching the application's S3_*_BUCKET env vars.

output "artifacts_bucket" {
  description = "S3_ARTIFACTS_BUCKET."
  value       = aws_s3_bucket.this["artifacts"].bucket
}

output "avatars_bucket" {
  description = "S3_AVATARS_BUCKET."
  value       = aws_s3_bucket.this["avatars"].bucket
}

output "reports_bucket" {
  description = "S3_REPORTS_BUCKET."
  value       = aws_s3_bucket.this["reports"].bucket
}

output "thumbnails_bucket" {
  description = "S3_THUMBNAILS_BUCKET."
  value       = aws_s3_bucket.this["thumbnails"].bucket
}
