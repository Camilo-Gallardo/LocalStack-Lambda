resource "aws_s3_bucket" "videos" {
  bucket        = "nuv-test-experto-nuvu-cv"  
  force_destroy = true
}

resource "aws_s3_bucket_public_access_block" "videos" {
  bucket                  = aws_s3_bucket.videos.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}
