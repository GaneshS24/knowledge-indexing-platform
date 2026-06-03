variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Deployment environment (dev, staging, prod)"
  type        = string
  default     = "prod"

  validation {
    condition     = contains(["dev", "staging", "prod"], var.environment)
    error_message = "environment must be dev, staging, or prod"
  }
}

variable "app_image" {
  description = "Docker image URI for the knowledge platform service"
  type        = string
  # e.g. 123456789012.dkr.ecr.us-east-1.amazonaws.com/knowledge-platform:latest
}

variable "db_password" {
  description = "RDS master password (store in Secrets Manager or TF_VAR)"
  type        = string
  sensitive   = true
}

variable "vpc_cidr" {
  description = "CIDR block for the VPC"
  type        = string
  default     = "10.0.0.0/16"
}

variable "ecs_desired_count" {
  description = "Desired number of ECS task instances"
  type        = number
  default     = 2
}

variable "ecs_cpu" {
  description = "ECS task CPU units (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 512
}

variable "ecs_memory" {
  description = "ECS task memory (MiB)"
  type        = number
  default     = 1024
}

variable "alarm_email" {
  description = "Email address for CloudWatch alarm notifications"
  type        = string
}
