variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "environment" {
  description = "Environment name"
  type        = string
  default     = "dev"
}

variable "project_name" {
  description = "Project name"
  type        = string
  default     = "docent"
}

variable "db_username" {
  description = "Database username"
  type        = string
  default     = "docent"
}

variable "db_password" {
  description = "Database password - used only for RDS instance creation, not exposed in application environment variables"
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "docent"
}

variable "app_runner_cpu" {
  description = "CPU units for App Runner (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 4096
}

variable "app_runner_memory" {
  description = "Memory for App Runner (512, 1024, 2048, 3072, 4096, 6144, 8192, 10240, 12288)"
  type        = number
  default     = 12288
}

variable "ecs_cpu" {
  description = "CPU units for ECS Fargate (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 4096
}

variable "ecs_memory" {
  description = "Memory for ECS Fargate (512, 1024, 2048, 3072, 4096, 5120, 6144, 7168, 8192)"
  type        = number
  default     = 8192
}

variable "worker_desired_count" {
  description = "Desired number of worker tasks"
  type        = number
  default     = 5
}
