# SSM Parameter Store for secrets
# These parameters are created from 1Password secrets and referenced at runtime
# by ECS tasks, App Runner, and EC2 instances.

resource "aws_ssm_parameter" "tailscale_auth_key" {
  name        = "/${var.project_name}/${var.deployment}/tailscale-auth-key"
  description = "Tailscale auth key for bastion and subnet router"
  type        = "SecureString"
  value       = local.tailscale_auth_key

  tags = {
    Name       = "${var.project_name}-${var.deployment}-tailscale-auth-key"
    Deployment = var.deployment
  }
}

resource "aws_ssm_parameter" "db_password" {
  name        = "/${var.project_name}/${var.deployment}/db-password"
  description = "PostgreSQL database password"
  type        = "SecureString"
  value       = local.db_password

  tags = {
    Name       = "${var.project_name}-${var.deployment}-db-password"
    Deployment = var.deployment
  }
}

resource "aws_ssm_parameter" "tailscale_oauth_client_id" {
  name        = "/${var.project_name}/${var.deployment}/tailscale-oauth-client-id"
  description = "Tailscale OAuth client ID for stale device cleanup"
  type        = "SecureString"
  value       = local.tailscale_oauth_client_id

  tags = {
    Name       = "${var.project_name}-${var.deployment}-tailscale-oauth-client-id"
    Deployment = var.deployment
  }
}

resource "aws_ssm_parameter" "tailscale_oauth_client_secret" {
  name        = "/${var.project_name}/${var.deployment}/tailscale-oauth-client-secret"
  description = "Tailscale OAuth client secret for stale device cleanup"
  type        = "SecureString"
  value       = local.tailscale_oauth_client_secret

  tags = {
    Name       = "${var.project_name}-${var.deployment}-tailscale-oauth-client-secret"
    Deployment = var.deployment
  }
}

resource "aws_ssm_parameter" "datadog_api_key" {
  name        = "/${var.project_name}/${var.deployment}/datadog-api-key"
  description = "Datadog API key"
  type        = "SecureString"
  value       = local.datadog_api_key

  tags = {
    Name       = "${var.project_name}-${var.deployment}-datadog-api-key"
    Deployment = var.deployment
  }
}
