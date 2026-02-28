###############################################################################
# ALB + ECS Fargate API service (conditional on var.use_ecs_api)
###############################################################################

# --- Application Load Balancer ---

resource "aws_lb" "api" {
  count = var.use_ecs_api ? 1 : 0

  name               = "${var.project_name}-${var.deployment}-api"
  internal           = false
  load_balancer_type = "application"
  security_groups    = [aws_security_group.alb[0].id]
  subnets            = aws_subnet.public[*].id

  tags = {
    Name       = "${var.project_name}-${var.deployment}-api-alb"
    Deployment = var.deployment
  }
}

resource "aws_lb_target_group" "api" {
  count = var.use_ecs_api ? 1 : 0

  name        = "${var.project_name}-${var.deployment}-api"
  port        = 8000
  protocol    = "HTTP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    path                = "/health"
    protocol            = "HTTP"
    port                = "traffic-port"
    healthy_threshold   = 3
    unhealthy_threshold = 3
    timeout             = 5
    interval            = 30
    matcher             = "200"
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-api-tg"
    Deployment = var.deployment
  }
}

# HTTPS listener (primary)
resource "aws_lb_listener" "api_https" {
  count = var.use_ecs_api && var.api_acm_certificate_arn != "" ? 1 : 0

  load_balancer_arn = aws_lb.api[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.api_acm_certificate_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api[0].arn
  }
}

# HTTP listener — redirect to HTTPS
resource "aws_lb_listener" "api_http" {
  count = var.use_ecs_api ? 1 : 0

  load_balancer_arn = aws_lb.api[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type = var.api_acm_certificate_arn != "" ? "redirect" : "forward"

    # When we have a cert, redirect HTTP -> HTTPS
    dynamic "redirect" {
      for_each = var.api_acm_certificate_arn != "" ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }

    # When there's no cert yet, forward directly (useful during initial setup)
    target_group_arn = var.api_acm_certificate_arn == "" ? aws_lb_target_group.api[0].arn : null
  }
}

# --- ECS Task Definition for API ---

resource "aws_ecs_task_definition" "api" {
  count = var.use_ecs_api ? 1 : 0

  family                   = "${var.project_name}-${var.deployment}-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_api_cpu
  memory                   = var.ecs_api_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "api"
      image = "${aws_ecr_repository.backend.repository_url}:latest"

      command = ["docent_core", "server", "--port", "8000", "--workers", tostring(var.ecs_api_num_workers), "--use-ddog"]

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
          value = "" # Disable cache
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
          awslogs-stream-prefix = "api"
        }
      }

      essential = true
    }
  ])

  tags = {
    Name       = "${var.project_name}-${var.deployment}-api-task"
    Deployment = var.deployment
  }
}

# --- ECS Service for API ---

resource "aws_ecs_service" "api" {
  count = var.use_ecs_api ? 1 : 0

  name            = "${var.project_name}-${var.deployment}-api"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.api[0].arn
  desired_count   = var.ecs_api_desired_count
  launch_type     = "FARGATE"

  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  lifecycle {
    ignore_changes = [desired_count]
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api[0].arn
    container_name   = "api"
    container_port   = 8000
  }

  depends_on = [
    aws_lb_listener.api_http,
    aws_lb_listener.api_https,
  ]

  tags = {
    Name       = "${var.project_name}-${var.deployment}-api-service"
    Deployment = var.deployment
  }
}

# --- Auto-scaling for ECS API ---

resource "aws_appautoscaling_target" "ecs_api" {
  count = var.use_ecs_api ? 1 : 0

  max_capacity       = var.ecs_api_max_size
  min_capacity       = var.ecs_api_min_size
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.api[0].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"

  tags = {
    Name       = "${var.project_name}-${var.deployment}-api-autoscaling-target"
    Deployment = var.deployment
  }
}

resource "aws_appautoscaling_policy" "ecs_api_cpu" {
  count = var.use_ecs_api ? 1 : 0

  name               = "${var.project_name}-${var.deployment}-api-cpu"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs_api[0].resource_id
  scalable_dimension = aws_appautoscaling_target.ecs_api[0].scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs_api[0].service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value       = 70
    scale_in_cooldown  = 300
    scale_out_cooldown = 60
  }
}

###############################################################################
# ALB CloudWatch Alarms (conditional on use_ecs_api)
###############################################################################

resource "aws_sns_topic" "alb_alerts" {
  count = var.use_ecs_api ? 1 : 0

  name = "${var.project_name}-${var.deployment}-alb-alerts"

  tags = {
    Deployment = var.deployment
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_unhealthy_hosts" {
  count = var.use_ecs_api ? 1 : 0

  alarm_name          = "${var.project_name}-${var.deployment}-alb-unhealthy-hosts"
  comparison_operator = "GreaterThanOrEqualToThreshold"
  evaluation_periods  = 2
  metric_name         = "UnHealthyHostCount"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Average"
  threshold           = 1
  alarm_description   = "ALB target group has unhealthy hosts"

  dimensions = {
    TargetGroup  = aws_lb_target_group.api[0].arn_suffix
    LoadBalancer = aws_lb.api[0].arn_suffix
  }

  alarm_actions = [aws_sns_topic.alb_alerts[0].arn]
  ok_actions    = [aws_sns_topic.alb_alerts[0].arn]

  tags = {
    Deployment = var.deployment
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_high_latency" {
  count = var.use_ecs_api ? 1 : 0

  alarm_name          = "${var.project_name}-${var.deployment}-alb-high-latency"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 3
  metric_name         = "TargetResponseTime"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Average"
  threshold           = 5
  alarm_description   = "ALB average response time exceeds 5 seconds"

  dimensions = {
    LoadBalancer = aws_lb.api[0].arn_suffix
  }

  alarm_actions = [aws_sns_topic.alb_alerts[0].arn]
  ok_actions    = [aws_sns_topic.alb_alerts[0].arn]

  tags = {
    Deployment = var.deployment
  }
}

resource "aws_cloudwatch_metric_alarm" "alb_5xx_errors" {
  count = var.use_ecs_api ? 1 : 0

  alarm_name          = "${var.project_name}-${var.deployment}-alb-5xx-errors"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "HTTPCode_ELB_5XX_Count"
  namespace           = "AWS/ApplicationELB"
  period              = 60
  statistic           = "Sum"
  threshold           = 10
  alarm_description   = "ALB 5xx error count exceeds 10"
  treat_missing_data  = "notBreaching"

  dimensions = {
    LoadBalancer = aws_lb.api[0].arn_suffix
  }

  alarm_actions = [aws_sns_topic.alb_alerts[0].arn]
  ok_actions    = [aws_sns_topic.alb_alerts[0].arn]

  tags = {
    Deployment = var.deployment
  }
}
