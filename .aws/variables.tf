variable "aws_region" {
  description = "AWS region to deploy into"
  type        = string
  default     = "us-west-1"
}

variable "key_name" {
  description = "Existing EC2 key pair name for SSH access"
  type        = string
  default     = "docent"
}

variable "instance_type" {
  description = "EC2 instance type"
  type        = string
  default     = "m5.8xlarge"
}

variable "root_volume_size" {
  description = "Size of the root EBS volume in GiB"
  type        = number
  default     = 200
}

variable "root_volume_type" {
  description = "Type of root EBS volume (gp3, gp2, io1, io2)"
  type        = string
  default     = "gp3"
}

variable "root_volume_encrypted" {
  description = "Whether to encrypt the root EBS volume"
  type        = bool
  default     = true
}

variable "db_username" {
  description = "Master username for Postgres"
  type        = string
  default     = "postgres"
}

variable "db_password" {
  description = "Master password for Postgres"
  type        = string
  sensitive   = true
}

variable "db_instance_class" {
  description = "RDS instance class"
  type        = string
  default     = "db.m5.8xlarge"
}

variable "db_allocated_storage" {
  description = "RDS storage (GiB)"
  type        = number
  default     = 200
}
