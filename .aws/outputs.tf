output "vpc_id" {
  description = "ID of the VPC"
  value       = aws_vpc.main.id
}

output "public_subnet_ids" {
  description = "IDs of the public subnets"
  value       = aws_subnet.public[*].id
}

output "private_subnet_ids" {
  description = "IDs of the private subnets"
  value       = aws_subnet.private[*].id
}

output "datadog_apm_nlb_dns_name" {
  description = "DNS name of the internal NLB fronting the Datadog agent APM endpoint"
  value       = aws_lb.datadog_agent.dns_name
}

output "rds_endpoint" {
  description = "RDS instance endpoint"
  value       = aws_db_instance.postgres.endpoint
  sensitive   = true
}

output "rds_port" {
  description = "RDS instance port"
  value       = aws_db_instance.postgres.port
}

output "database_password_ssm_arn" {
  description = "ARN of the SSM parameter containing the database password"
  value       = aws_ssm_parameter.db_password.arn
  sensitive   = true
}

output "redis_endpoint" {
  description = "ElastiCache Redis primary endpoint"
  value       = aws_elasticache_replication_group.redis.primary_endpoint_address
  sensitive   = true
}

output "redis_port" {
  description = "ElastiCache Redis port"
  value       = aws_elasticache_replication_group.redis.port
}

output "app_runner_service_url" {
  description = "App Runner service URL"
  value       = var.use_ecs_api ? null : "https://${aws_apprunner_service.api[0].service_url}"
}

output "app_runner_service_arn" {
  description = "App Runner service ARN"
  value       = var.use_ecs_api ? null : aws_apprunner_service.api[0].arn
}

output "api_alb_dns_name" {
  description = "DNS name of the API ALB (when using ECS API)"
  value       = var.use_ecs_api ? aws_lb.api[0].dns_name : null
}

output "backend_ecr_repository_url" {
  description = "ECR repository URL for backend (server and worker)"
  value       = aws_ecr_repository.backend.repository_url
}

output "ecs_cluster_name" {
  description = "ECS cluster name"
  value       = aws_ecs_cluster.main.name
}

output "ecs_service_name" {
  description = "ECS service names keyed by worker type"
  value       = { for key, svc in aws_ecs_service.worker : key => svc.name }
}

output "bastion_public_ip" {
  value       = aws_instance.bastion.public_ip
  description = "Public IP address of the bastion host"
}

output "bastion_public_dns" {
  value       = aws_instance.bastion.public_dns
  description = "Public DNS name of the bastion host"
}

output "private_api_nlb_dns" {
  description = "Internal NLB DNS name for the private API"
  value       = var.use_private_api ? aws_lb.private_api[0].dns_name : null
}

output "vpc_endpoint_service_name" {
  description = "PrivateLink service name for external accounts to create VPC endpoints"
  value       = var.use_private_api ? aws_vpc_endpoint_service.private_api[0].service_name : null
}

output "api_gateway_url" {
  description = "API Gateway invoke URL for Vercel SSR"
  value       = var.use_private_api ? aws_apigatewayv2_api.private_api[0].api_endpoint : null
}
