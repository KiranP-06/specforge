resource "random_id" "suffix" { byte_length = 3 }

# Uploaded briefs, exports and nightly Postgres backups.
resource "aws_s3_bucket" "app" {
  bucket        = "${var.project}-app-${random_id.suffix.hex}"
  force_destroy = true # lab environment: allow `terraform destroy` to empty it
}

resource "aws_s3_bucket_public_access_block" "app" {
  bucket                  = aws_s3_bucket.app.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_versioning" "app" {
  bucket = aws_s3_bucket.app.id
  versioning_configuration { status = "Enabled" }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "app" {
  bucket = aws_s3_bucket.app.id
  rule {
    apply_server_side_encryption_by_default { sse_algorithm = "AES256" }
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "app" {
  bucket = aws_s3_bucket.app.id
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
