resource "aws_apprunner_vpc_connector" "main" {
  vpc_connector_name = "${var.project_name}-${var.deployment}-vpc-connector"
  subnets            = aws_subnet.private[*].id
  security_groups    = [aws_security_group.app_runner.id]

  tags = {
    Name        = "${var.project_name}-${var.deployment}-vpc-connector"
    Deployment = var.deployment
  }
}

resource "aws_iam_role" "app_runner_instance" {
  name = "${var.project_name}-${var.deployment}-app-runner-instance-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "tasks.apprunner.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-${var.deployment}-app-runner-instance-role"
    Deployment = var.deployment
  }
}

# Allow App Runner instance role to read secrets from SSM Parameter Store
resource "aws_iam_role_policy" "app_runner_instance_secrets" {
  name = "${var.project_name}-${var.deployment}-app-runner-instance-secrets"
  role = aws_iam_role.app_runner_instance.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadSSMParameters"
        Effect = "Allow"
        Action = [
          "ssm:GetParameters",
          "ssm:GetParameter"
        ]
        Resource = [
          "arn:aws:ssm:${var.aws_region}:${data.aws_caller_identity.current.account_id}:parameter/${var.project_name}/${var.deployment}/*"
        ]
      },
      {
        Sid    = "DecryptSecrets"
        Effect = "Allow"
        Action = [
          "kms:Decrypt"
        ]
        Resource = "*"
        Condition = {
          StringEquals = {
            "kms:ViaService" = "ssm.${var.aws_region}.amazonaws.com"
          }
        }
      }
    ]
  })
}

resource "aws_iam_role" "app_runner_access" {
  name = "${var.project_name}-${var.deployment}-app-runner-access-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "build.apprunner.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-${var.deployment}-app-runner-access-role"
    Deployment = var.deployment
  }
}

resource "aws_iam_role_policy_attachment" "app_runner_access_ecr" {
  role       = aws_iam_role.app_runner_access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

resource "aws_apprunner_service" "api" {
  service_name = "${var.project_name}-${var.deployment}-api"

  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.app_runner_access.arn
    }
    image_repository {
      image_identifier      = "${aws_ecr_repository.backend.repository_url}:latest"
      image_configuration {
        port = "8000"
        start_command = "docent_core server --port 8000 --workers ${var.app_runner_num_workers} --use-ddog"
        runtime_environment_variables = {
          ENV_RESOLUTION_STRATEGY = "os_environ"
          DEPLOYMENT_ID           = var.deployment
          LLM_CACHE_PATH          = null # Disable cache
          DOCENT_PG_HOST          = aws_db_instance.postgres.address
          DOCENT_PG_PORT          = aws_db_instance.postgres.port
          DOCENT_PG_DATABASE      = var.db_name
          DOCENT_PG_USER          = var.db_username
          DOCENT_REDIS_HOST       = aws_elasticache_replication_group.redis.primary_endpoint_address
          DOCENT_REDIS_PORT       = aws_elasticache_replication_group.redis.port
          DOCENT_REDIS_TLS        = "true"
          DD_AGENT_HOST           = aws_lb.datadog_agent.dns_name
          DD_AGENT_PORT           = "8126"
          DD_ENV                  = var.deployment
          DD_SERVICE              = "docent-app"
        }
        runtime_environment_secrets = {
          DOCENT_PG_PASSWORD = aws_ssm_parameter.db_password.arn
        }
      }
      image_repository_type = "ECR"
    }
    auto_deployments_enabled = false
  }

  instance_configuration {
    cpu               = var.app_runner_cpu
    memory            = var.app_runner_memory
    instance_role_arn = aws_iam_role.app_runner_instance.arn
  }

  network_configuration {
    egress_configuration {
      egress_type       = "VPC"
      vpc_connector_arn = aws_apprunner_vpc_connector.main.arn
    }
  }

  health_check_configuration {
    healthy_threshold   = 1
    interval            = 10
    path                = "/health"
    protocol            = "HTTP"
    timeout             = 5
    unhealthy_threshold = 5
  }

  auto_scaling_configuration_arn = aws_apprunner_auto_scaling_configuration_version.api.arn

  tags = {
    Name        = "${var.project_name}-${var.deployment}-api"
    Deployment = var.deployment
  }
}

resource "aws_apprunner_auto_scaling_configuration_version" "api" {
  auto_scaling_configuration_name = "${var.project_name}-${var.deployment}-api-autoscaling"

  max_concurrency = var.app_runner_max_concurrency
  max_size        = var.app_runner_max_size
  min_size        = var.app_runner_min_size

  lifecycle {
    create_before_destroy = true
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-api-autoscaling"
    Deployment = var.deployment
  }
}
