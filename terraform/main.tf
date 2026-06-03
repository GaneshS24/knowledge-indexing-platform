# ─────────────────────────────────────────────────────────────────────────────
# Knowledge Indexing Platform — Infrastructure as Code
#
# Primary target: AWS (ECS + RDS + S3) because the assessment specifies AWS.
# Design mirrors patterns from OCI production work:
#   - Object Storage for raw blobs (same as Exadata image replication)
#   - KMS for per-tenant key management (same as OCI Vault integration)
#   - IAM policies for cross-service access (same as cross-tenancy backup/restore)
#   - Multi-region provisioning via replication (same as gold-image pipeline)
# ─────────────────────────────────────────────────────────────────────────────

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Remote state — same pattern as Exadata provisioning state management
  # backend "s3" {
  #   bucket         = "knowledge-platform-tfstate"
  #   key            = "knowledge-platform/terraform.tfstate"
  #   region         = var.aws_region
  #   dynamodb_table = "terraform-locks"
  #   encrypt        = true
  # }
}

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      Project     = "knowledge-platform"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}
