# Learner Lab denies s3:GetBucketObjectLockConfiguration, so Terraform cannot manage
# aws_s3_bucket directly. The bucket is created once with the AWS CLI and read here.
variable "app_bucket" {
  description = "Existing app bucket (create first: aws s3api create-bucket --bucket <name>)"
  type        = string
}

# Uploaded briefs, exports and nightly Postgres backups.
data "aws_s3_bucket" "app" {
  bucket = var.app_bucket
}

resource "aws_s3_bucket_public_access_block" "app" {
  bucket                  = data.aws_s3_bucket.app.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "app" {
  bucket = data.aws_s3_bucket.app.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "app" {
  bucket = data.aws_s3_bucket.app.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "app" {
  bucket = data.aws_s3_bucket.app.id
  rule {
    id     = "expire-old-backups"
    status = "Enabled"
    filter { prefix = "backups/" }
    expiration { days = 30 }
    noncurrent_version_expiration { noncurrent_days = 7 }
  }
  rule {
    id     = "expire-old-exports"
    status = "Enabled"
    filter { prefix = "exports/" }
    expiration { days = 14 }
  }
}
