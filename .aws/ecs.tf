resource "aws_ecs_cluster" "main" {
  name = "${var.project_name}-${var.deployment}-cluster"

  configuration {
    execute_command_configuration {
      logging = "OVERRIDE"
      log_configuration {
        cloud_watch_log_group_name = aws_cloudwatch_log_group.ecs.name
      }
    }
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-cluster"
    Deployment = var.deployment
  }
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_name}-${var.deployment}"
  retention_in_days = 365

  tags = {
    Name       = "${var.project_name}-${var.deployment}-ecs-logs"
    Deployment = var.deployment
  }
}

resource "aws_iam_role" "ecs_task_execution" {
  name = "${var.project_name}-${var.deployment}-ecs-task-execution-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name       = "${var.project_name}-${var.deployment}-ecs-task-execution-role"
    Deployment = var.deployment
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# Allow ECS task execution role to read secrets from SSM and Secrets Manager
resource "aws_iam_role_policy" "ecs_task_execution_secrets" {
  name = "${var.project_name}-${var.deployment}-ecs-task-execution-secrets"
  role = aws_iam_role.ecs_task_execution.id

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


resource "aws_iam_role" "ecs_task" {
  name = "${var.project_name}-${var.deployment}-ecs-task-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ecs-tasks.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name       = "${var.project_name}-${var.deployment}-ecs-task-role"
    Deployment = var.deployment
  }
}

resource "aws_iam_role_policy" "ecs_task_metrics" {
  name = "${var.project_name}-${var.deployment}-ecs-task-metrics"
  role = aws_iam_role.ecs_task.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = [
          "cloudwatch:PutMetricData",
        ]
        Effect   = "Allow"
        Resource = "*"
        Condition = {
          StringEquals = {
            "cloudwatch:namespace" = "Docent/Workers"
          }
        }
      }
    ]
  })
}

locals {
  worker_queue_base_configs = {
    default = {
      service_suffix = "worker"
      container_name = "worker"
      queue_name     = "docent_worker_queue"
      desired_count  = var.ecs_desired_count
      min_size       = var.ecs_min_size
      max_size       = var.ecs_max_size
    }
    telemetry_processing = {
      service_suffix = "telemetry-processing-worker"
      container_name = "telemetry-processing-worker"
      queue_name     = "docent_worker_queue:telemetry_processing"
      desired_count  = var.telemetry_processing_ecs_desired_count
      min_size       = var.telemetry_processing_ecs_min_size
      max_size       = var.telemetry_processing_ecs_max_size
    }
    telemetry_ingest = {
      service_suffix = "telemetry-ingest-worker"
      container_name = "telemetry-ingest-worker"
      queue_name     = "docent_worker_queue:telemetry_ingest"
      desired_count  = var.telemetry_ingest_ecs_desired_count
      min_size       = var.telemetry_ingest_ecs_min_size
      max_size       = var.telemetry_ingest_ecs_max_size
    }
  }

  worker_queue_configs = {
    for queue_name, config in local.worker_queue_base_configs :
    queue_name => merge(config, {
      num_workers  = lookup(var.ecs_workers_per_queue, queue_name, var.ecs_default_workers)
      target_depth = lookup(var.worker_queue_target_depths, queue_name, var.worker_queue_target_depth)
    })
  }
}

resource "aws_ecs_task_definition" "worker" {
  for_each                 = local.worker_queue_configs
  family                   = "${var.project_name}-${var.deployment}-${each.value.service_suffix}"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_cpu
  memory                   = var.ecs_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = each.value.container_name
      image = "${aws_ecr_repository.backend.repository_url}:latest"

      command = ["docent_core", "worker", "--workers", tostring(each.value.num_workers)]

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
          name  = "DOCENT_WORKER_QUEUE_NAME"
          value = each.value.queue_name
        }
      ]

      secrets = [
        {
          name      = "DOCENT_PG_PASSWORD"
          valueFrom = aws_ssm_parameter.db_password.arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = each.value.service_suffix
        }
      }

      essential = true
    }
  ])

  tags = {
    Name       = "${var.project_name}-${var.deployment}-${each.value.service_suffix}-task"
    Deployment = var.deployment
    Queue      = each.value.queue_name
  }
}

resource "aws_ecs_service" "worker" {
  for_each        = local.worker_queue_configs
  name            = "${var.project_name}-${var.deployment}-${each.value.service_suffix}"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker[each.key].arn
  desired_count   = coalesce(each.value.desired_count, 1)
  launch_type     = "FARGATE"

  lifecycle {
    ignore_changes = [desired_count]
  }

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-${each.value.service_suffix}-service"
    Deployment = var.deployment
    Queue      = each.value.queue_name
  }
}

resource "aws_lb" "datadog_agent" {
  name               = "${var.project_name}-${var.deployment}-dd-apm"
  internal           = true
  load_balancer_type = "network"
  subnets            = aws_subnet.private[*].id

  enable_cross_zone_load_balancing = true

  tags = {
    Name       = "${var.project_name}-${var.deployment}-datadog-agent-nlb"
    Deployment = var.deployment
    Role       = "datadog-agent"
  }
}

resource "aws_lb_target_group" "datadog_agent" {
  name        = "${var.project_name}-${var.deployment}-dd-apm"
  port        = 8126
  protocol    = "TCP"
  target_type = "ip"
  vpc_id      = aws_vpc.main.id

  health_check {
    protocol = "TCP"
    port     = "8126"
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-datadog-agent-tg"
    Deployment = var.deployment
    Role       = "datadog-agent"
  }
}

resource "aws_lb_listener" "datadog_agent" {
  load_balancer_arn = aws_lb.datadog_agent.arn
  port              = 8126
  protocol          = "TCP"

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.datadog_agent.arn
  }
}

resource "aws_ecs_service" "datadog_agent" {
  name            = "${var.project_name}-${var.deployment}-datadog-agent"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.datadog_agent.arn
  desired_count   = var.datadog_agent_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.datadog_agent.id]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.datadog_agent.arn
    container_name   = "datadog-agent"
    container_port   = 8126
  }

  depends_on = [
    aws_lb_listener.datadog_agent
  ]

  tags = {
    Name       = "${var.project_name}-${var.deployment}-datadog-agent-service"
    Deployment = var.deployment
    Role       = "datadog-agent"
  }
}

resource "aws_ecs_task_definition" "datadog_agent" {
  family                   = "${var.project_name}-${var.deployment}-datadog-agent"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.datadog_agent_cpu
  memory                   = var.datadog_agent_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "datadog-agent"
      image = "public.ecr.aws/datadog/agent:latest"

      environment = [
        {
          name  = "DD_SITE"
          value = var.datadog_site
        },
        {
          name  = "DD_ECS_FARGATE"
          value = "true"
        },
        {
          name  = "ECS_FARGATE"
          value = "true"
        },
        {
          name  = "DD_LOGS_ENABLED"
          value = "true"
        },
        {
          name  = "DD_APM_ENABLED"
          value = "true"
        },
        {
          name  = "DD_APM_NON_LOCAL_TRAFFIC"
          value = "true"
        },
        {
          name  = "DD_PROCESS_AGENT_ENABLED"
          value = "true"
        }
      ]

      secrets = [
        {
          name      = "DD_API_KEY"
          valueFrom = aws_ssm_parameter.datadog_api_key.arn
        }
      ]

      portMappings = [
        {
          containerPort = 8126
          hostPort      = 8126
          protocol      = "tcp"
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "datadog-agent"
        }
      }

      essential = true
    }
  ])

  tags = {
    Name       = "${var.project_name}-${var.deployment}-datadog-agent-task"
    Deployment = var.deployment
    Role       = "datadog-agent"
  }
}

resource "aws_appautoscaling_target" "ecs_worker" {
  for_each           = local.worker_queue_configs
  max_capacity       = each.value.max_size
  min_capacity       = each.value.min_size
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.worker[each.key].name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"

  tags = {
    Name       = "${var.project_name}-${var.deployment}-${each.value.service_suffix}-autoscaling-target"
    Deployment = var.deployment
    Queue      = each.value.queue_name
  }
}

resource "aws_appautoscaling_policy" "ecs_worker_queue_depth" {
  for_each           = local.worker_queue_configs
  name               = "${var.project_name}-${var.deployment}-${each.value.service_suffix}-queue-depth"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs_worker[each.key].resource_id
  scalable_dimension = aws_appautoscaling_target.ecs_worker[each.key].scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs_worker[each.key].service_namespace

  target_tracking_scaling_policy_configuration {
    customized_metric_specification {
      metric_name = "QueueDepth"
      namespace   = "Docent/Workers"
      statistic   = "Average"
      unit        = "Count"

      dimensions {
        name  = "QueueName"
        value = each.value.queue_name
      }

      dimensions {
        name  = "Deployment"
        value = var.deployment
      }
    }
    target_value       = each.value.target_depth
    scale_in_cooldown  = var.worker_queue_scale_in_cooldown
    scale_out_cooldown = var.worker_queue_scale_out_cooldown
  }
}

resource "aws_ecs_task_definition" "migrations" {
  family                   = "${var.project_name}-${var.deployment}-migrations"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_cpu
  memory                   = var.ecs_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn            = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "migrations"
      image = "${aws_ecr_repository.backend.repository_url}:latest"

      command = ["/bin/sh", "-c", "alembic upgrade head"]

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
        }
      ]

      secrets = [
        {
          name      = "DOCENT_PG_PASSWORD"
          valueFrom = aws_ssm_parameter.db_password.arn
        }
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "migrations"
        }
      }

      essential = true
    }
  ])

  tags = {
    Name       = "${var.project_name}-${var.deployment}-migrations-task"
    Deployment = var.deployment
  }
}
