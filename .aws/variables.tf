variable "aws_region" {
  description = "AWS region"
  type        = string
  default     = "us-east-1"
}

variable "deployment" {
  description = "Deployment name"
  type        = string
}

variable "project_name" {
  description = "Project name"
  type        = string
  default     = "docent"
}

variable "public_subnet_count" {
  description = "Number of public subnets to create"
  type        = number
}

variable "private_subnet_count" {
  description = "Number of private subnets to create (minimum 2)"
  type        = number
  validation {
    condition     = var.private_subnet_count >= 2
    error_message = "The minimum value for private_subnet_count is 2, for RDS and Elasticache."
  }
}

variable "nat_gateway_count" {
  description = "Number of NAT gateways to create (must be less than or equal to number of public subnets)"
  type        = number
  validation {
    condition     = var.nat_gateway_count <= var.public_subnet_count
    error_message = "The number of NAT gateways must be less than or equal to the number of public subnets."
  }
}

variable "elasticache_node_type" {
  description = "Elasticache node type"
  type        = string
}

variable "rds_instance_class" {
  description = "RDS instance class"
  type        = string
}

variable "db_username" {
  description = "Database username"
  type        = string
  default     = "docent_user"
}

variable "db_password" {
  description = "Database password - used only for RDS instance creation, not exposed in application environment variables"
  type        = string
  sensitive   = true
}

variable "db_name" {
  description = "Database name"
  type        = string
  default     = "docent_db"
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

variable "app_runner_max_concurrency" {
  description = "Maximum concurrency for App Runner"
  type        = number
}

variable "app_runner_min_size" {
  description = "Minimum number of App Runner instances"
  type        = number
}

variable "app_runner_max_size" {
  description = "Maximum number of App Runner instances"
  type        = number
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
}

variable "bastion_public_key" {
  description = "SSH public key for bastion host access (e.g., contents of ~/.ssh/id_rsa.pub). If empty, bastion host will not be created."
  type        = string
  default     = ""
}

variable "tailscale_auth_key" {
  description = "Tailscale auth key for subnet router (only used in METR deployment)"
  type        = string
  sensitive   = true
  default     = ""
}

variable "enable_frontend_app_runner" {
  description = "Enable App Runner deployment for the Next.js frontend"
  type        = bool
  default     = false
}

variable "frontend_app_runner_cpu" {
  description = "CPU units for Frontend App Runner (256, 512, 1024, 2048, 4096)"
  type        = number
  default     = 1024
}

variable "frontend_app_runner_memory" {
  description = "Memory for Frontend App Runner (512, 1024, 2048, 3072, 4096, 6144, 8192, 10240, 12288)"
  type        = number
  default     = 2048
}

variable "frontend_app_runner_max_concurrency" {
  description = "Maximum concurrency for Frontend App Runner"
  type        = number
  default     = 100
}

variable "frontend_app_runner_min_size" {
  description = "Minimum number of Frontend App Runner instances"
  type        = number
  default     = 1
}

variable "frontend_app_runner_max_size" {
  description = "Maximum number of Frontend App Runner instances"
  type        = number
  default     = 10
}
