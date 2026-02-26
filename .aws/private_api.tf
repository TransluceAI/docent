###############################################################################
# Private API: NLB + ECS Fargate + PrivateLink + API Gateway
#
# Deploys the API behind an internal NLB accessible via PrivateLink for
# direct VPC-to-VPC access, and an API Gateway as a restricted public proxy
# for Vercel SSR calls. All resources gated on var.use_private_api.
###############################################################################

# --- Security Group ---

resource "aws_security_group" "private_api" {
  count = var.use_private_api ? 1 : 0

  name_prefix = "${var.project_name}-${var.deployment}-private-api-"
  vpc_id      = aws_vpc.main.id

  # NLBs forward traffic with the original source IP preserved for targets
  # in the same VPC, so we allow the entire VPC CIDR.
  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr_block]
    description = "API traffic from NLB (VPC CIDR)"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-private-api-sg"
    Deployment = var.deployment
  }

  lifecycle {
    create_before_destroy = true
  }
}

# --- Internal Network Load Balancer ---

resource "aws_lb" "private_api" {
  count = var.use_private_api ? 1 : 0

  name               = "${var.project_name}-${var.deployment}-priv-api"
  internal           = true
  load_balancer_type = "network"
  subnets            = aws_subnet.private[*].id

  enable_cross_zone_load_balancing = true

  tags = {
    Name       = "${var.project_name}-${var.deployment}-private-api-nlb"
    Deployment = var.deployment
  }
}

resource "aws_lb_target_group" "private_api" {
  count = var.use_private_api ? 1 : 0

  name        = "${var.project_name}-${var.deployment}-priv-api"
  port        = 8000
  protocol    = "TCP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    protocol            = "HTTP"
    path                = "/health"
    port                = "traffic-port"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    interval            = 30
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-private-api-tg"
    Deployment = var.deployment
  }
}

resource "aws_lb_listener" "private_api" {
  count = var.use_private_api ? 1 : 0

  load_balancer_arn = aws_lb.private_api[0].arn
  port              = 8000
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.private_api[0].arn
  }
}

# --- ECS Task Definition ---

resource "aws_ecs_task_definition" "private_api" {
  count = var.use_private_api ? 1 : 0

  family                   = "${var.project_name}-${var.deployment}-private-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.private_api_cpu
  memory                   = var.private_api_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "api"
      image = "${aws_ecr_repository.backend.repository_url}:latest"

      command = ["docent_core", "server", "--port", "8000", "--workers", tostring(var.private_api_num_workers), "--use-ddog"]

      environment = [
        {
          name  = "ENV_RESOLUTION_STRATEGY"
          value = "os_environ"
        },
        {
          name  = "DEPLOYMENT_ID"
          value = var.deployment
        },
        {
          name  = "LLM_CACHE_PATH"
          value = ""
        },
        {
          name  = "DOCENT_PG_HOST"
          value = aws_db_instance.postgres.address
        },
        {
          name  = "DOCENT_PG_PORT"
          value = tostring(aws_db_instance.postgres.port)
        },
        {
          name  = "DOCENT_PG_DATABASE"
          value = var.db_name
        },
        {
          name  = "DOCENT_PG_USER"
          value = var.db_username
        },
        {
          name  = "DOCENT_REDIS_HOST"
          value = aws_elasticache_replication_group.redis.primary_endpoint_address
        },
        {
          name  = "DOCENT_REDIS_PORT"
          value = tostring(aws_elasticache_replication_group.redis.port)
        },
        {
          name  = "DOCENT_REDIS_TLS"
          value = "true"
        },
        {
          name  = "DD_AGENT_HOST"
          value = aws_lb.datadog_agent.dns_name
        },
        {
          name  = "DD_AGENT_PORT"
          value = "8126"
        },
        {
          name  = "DD_ENV"
          value = var.deployment
        },
        {
          name  = "DD_SERVICE"
          value = "docent-app"
        }
      ]

      secrets = [
        {
          name      = "DOCENT_PG_PASSWORD"
          valueFrom = aws_ssm_parameter.db_password.arn
        }
      ]

      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
          protocol      = "tcp"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "private-api"
        }
      }

      essential = true
    }
  ])

  tags = {
    Name       = "${var.project_name}-${var.deployment}-private-api-task"
    Deployment = var.deployment
  }
}

# --- ECS Service ---

resource "aws_ecs_service" "private_api" {
  count = var.use_private_api ? 1 : 0

  name            = "${var.project_name}-${var.deployment}-private-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.private_api[0].arn
  desired_count   = var.ecs_api_desired_count
  launch_type     = "FARGATE"

  lifecycle {
    ignore_changes = [desired_count]
  }

  network_configuration {
    subnets = aws_subnet.private[*].id
    security_groups = [
      aws_security_group.private_api[0].id,
      aws_security_group.ecs_tasks.id,
    ]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.private_api[0].arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [aws_lb_listener.private_api]

  tags = {
    Name       = "${var.project_name}-${var.deployment}-private-api-service"
    Deployment = var.deployment
  }
}

# --- Auto-scaling ---

resource "aws_appautoscaling_target" "private_api" {
  count = var.use_private_api ? 1 : 0

  max_capacity       = var.ecs_api_max_size
  min_capacity       = var.ecs_api_min_size
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.private_api[0].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"

  tags = {
    Name       = "${var.project_name}-${var.deployment}-private-api-autoscaling-target"
    Deployment = var.deployment
  }
}

resource "aws_appautoscaling_policy" "private_api_cpu" {
  count = var.use_private_api ? 1 : 0

  name               = "${var.project_name}-${var.deployment}-private-api-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.private_api[0].resource_id
  scalable_dimension = aws_appautoscaling_target.private_api[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.private_api[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

# --- VPC Endpoint Service (PrivateLink) ---

resource "aws_vpc_endpoint_service" "private_api" {
  count = var.use_private_api ? 1 : 0

  acceptance_required        = var.privatelink_acceptance_required
  network_load_balancer_arns = [aws_lb.private_api[0].arn]
  allowed_principals         = var.privatelink_allowed_principals

  tags = {
    Name       = "${var.project_name}-${var.deployment}-private-api-endpoint-service"
    Deployment = var.deployment
  }
}

# --- API Gateway HTTP API (public proxy for Vercel SSR) ---

resource "aws_apigatewayv2_api" "private_api" {
  count = var.use_private_api ? 1 : 0

  name          = "${var.project_name}-${var.deployment}-private-api-gw"
  protocol_type = "HTTP"

  tags = {
    Name       = "${var.project_name}-${var.deployment}-private-api-gw"
    Deployment = var.deployment
  }
}

resource "aws_security_group" "api_gateway_vpc_link" {
  count = var.use_private_api ? 1 : 0

  name_prefix = "${var.project_name}-${var.deployment}-apigw-vpclink-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 8000
    to_port     = 8000
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr_block]
    description = "API Gateway VPC Link traffic"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-apigw-vpclink-sg"
    Deployment = var.deployment
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_apigatewayv2_vpc_link" "private_api" {
  count = var.use_private_api ? 1 : 0

  name               = "${var.project_name}-${var.deployment}-private-api"
  subnet_ids         = aws_subnet.private[*].id
  security_group_ids = [aws_security_group.api_gateway_vpc_link[0].id]

  tags = {
    Name       = "${var.project_name}-${var.deployment}-private-api-vpclink"
    Deployment = var.deployment
  }
}

resource "aws_apigatewayv2_integration" "private_api" {
  count = var.use_private_api ? 1 : 0

  api_id             = aws_apigatewayv2_api.private_api[0].id
  integration_type   = "HTTP_PROXY"
  integration_method = "ANY"
  integration_uri    = aws_lb_listener.private_api[0].arn
  connection_type    = "VPC_LINK"
  connection_id      = aws_apigatewayv2_vpc_link.private_api[0].id
}

resource "aws_apigatewayv2_route" "private_api" {
  count = var.use_private_api ? 1 : 0

  api_id    = aws_apigatewayv2_api.private_api[0].id
  route_key = "$default"
  target    = "integrations/${aws_apigatewayv2_integration.private_api[0].id}"
}

resource "aws_apigatewayv2_stage" "private_api" {
  count = var.use_private_api ? 1 : 0

  api_id      = aws_apigatewayv2_api.private_api[0].id
  name        = "$default"
  auto_deploy = true

  tags = {
    Name       = "${var.project_name}-${var.deployment}-private-api-gw-stage"
    Deployment = var.deployment
  }
}

# IP-based access restriction via WAFv2 (API Gateway HTTP APIs don't support
# resource policies, so we use a regional WAF web ACL instead).

resource "aws_wafv2_ip_set" "api_gateway_allowed" {
  count = var.use_private_api && length(var.api_gateway_allowed_cidrs) > 0 ? 1 : 0

  name               = "${var.project_name}-${var.deployment}-apigw-allowed-ips"
  scope              = "REGIONAL"
  ip_address_version = "IPV4"
  addresses          = var.api_gateway_allowed_cidrs

  tags = {
    Name       = "${var.project_name}-${var.deployment}-apigw-allowed-ips"
    Deployment = var.deployment
  }
}

resource "aws_wafv2_web_acl" "api_gateway" {
  count = var.use_private_api && length(var.api_gateway_allowed_cidrs) > 0 ? 1 : 0

  name  = "${var.project_name}-${var.deployment}-apigw-waf"
  scope = "REGIONAL"

  default_action {
    block {}
  }

  rule {
    name     = "allow-listed-ips"
    priority = 1

    action {
      allow {}
    }

    statement {
      ip_set_reference_statement {
        arn = aws_wafv2_ip_set.api_gateway_allowed[0].arn
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "${var.project_name}-${var.deployment}-apigw-allowed-ips"
      sampled_requests_enabled   = true
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${var.project_name}-${var.deployment}-apigw-waf"
    sampled_requests_enabled   = true
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-apigw-waf"
    Deployment = var.deployment
  }
}

resource "aws_wafv2_web_acl_association" "api_gateway" {
  count = var.use_private_api && length(var.api_gateway_allowed_cidrs) > 0 ? 1 : 0

  resource_arn = aws_apigatewayv2_stage.private_api[0].arn
  web_acl_arn  = aws_wafv2_web_acl.api_gateway[0].arn
}
