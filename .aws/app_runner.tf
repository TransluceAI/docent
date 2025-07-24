resource "aws_apprunner_vpc_connector" "main" {
  vpc_connector_name = "${var.project_name}-${var.environment}-vpc-connector"
  subnets            = aws_subnet.private[*].id
  security_groups    = [aws_security_group.app_runner.id]

  tags = {
    Name        = "${var.project_name}-${var.environment}-vpc-connector"
    Environment = var.environment
  }
}

resource "aws_iam_role" "app_runner_instance" {
  name = "${var.project_name}-${var.environment}-app-runner-instance-role"

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
    Name        = "${var.project_name}-${var.environment}-app-runner-instance-role"
    Environment = var.environment
  }
}

resource "aws_iam_role" "app_runner_access" {
  name = "${var.project_name}-${var.environment}-app-runner-access-role"

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
    Name        = "${var.project_name}-${var.environment}-app-runner-access-role"
    Environment = var.environment
  }
}

resource "aws_iam_role_policy_attachment" "app_runner_access_ecr" {
  role       = aws_iam_role.app_runner_access.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSAppRunnerServicePolicyForECRAccess"
}

resource "aws_apprunner_service" "api" {
  service_name = "${var.project_name}-${var.environment}-api"

  source_configuration {
    authentication_configuration {
      access_role_arn = aws_iam_role.app_runner_access.arn
    }
    image_repository {
      image_identifier      = "${aws_ecr_repository.backend.repository_url}:latest"
      image_configuration {
        port = "8000"
        runtime_environment_variables = {
          SERVICE              = "server"  # Starts the uvicorn server, not the worker
          ENVIRONMENT          = var.environment
          LLM_CACHE_PATH       = ""  # Disable cache
          DOCENT_PG_HOST       = aws_db_instance.postgres.address
          DOCENT_PG_PORT       = aws_db_instance.postgres.port
          DOCENT_PG_NAME       = var.db_name
          DOCENT_PG_USER       = var.db_username
          DOCENT_PG_PASSWORD   = var.db_password
          DOCENT_REDIS_HOST    = aws_elasticache_replication_group.redis.primary_endpoint_address
          DOCENT_REDIS_PORT    = aws_elasticache_replication_group.redis.port
          DOCENT_REDIS_TLS     = "true"
          DOCENT_CORS_ORIGINS  = "https://${var.environment}.transluce.org"
        }
      }
      image_repository_type = "ECR"
    }
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
    path                = "/"
    protocol            = "HTTP"
    timeout             = 5
    unhealthy_threshold = 5
  }

  auto_scaling_configuration_arn = aws_apprunner_auto_scaling_configuration_version.api.arn

  tags = {
    Name        = "${var.project_name}-${var.environment}-api"
    Environment = var.environment
  }
}

resource "aws_apprunner_auto_scaling_configuration_version" "api" {
  auto_scaling_configuration_name = "${var.project_name}-${var.environment}-api-autoscaling"

  max_concurrency = 100
  max_size        = 10
  min_size        = 1

  tags = {
    Name        = "${var.project_name}-${var.environment}-api-autoscaling"
    Environment = var.environment
  }
}
