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
    Name        = "${var.project_name}-${var.deployment}-cluster"
    Deployment = var.deployment
  }
}

resource "aws_cloudwatch_log_group" "ecs" {
  name              = "/ecs/${var.project_name}-${var.deployment}"
  retention_in_days = 7

  tags = {
    Name        = "${var.project_name}-${var.deployment}-ecs-logs"
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
    Name        = "${var.project_name}-${var.deployment}-ecs-task-execution-role"
    Deployment = var.deployment
  }
}

resource "aws_iam_role_policy_attachment" "ecs_task_execution" {
  role       = aws_iam_role.ecs_task_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
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
    Name        = "${var.project_name}-${var.deployment}-ecs-task-role"
    Deployment = var.deployment
  }
}

resource "aws_ecs_task_definition" "worker" {
  family                   = "${var.project_name}-${var.deployment}-worker"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = var.ecs_cpu
  memory                   = var.ecs_memory
  execution_role_arn       = aws_iam_role.ecs_task_execution.arn
  task_role_arn           = aws_iam_role.ecs_task.arn

  container_definitions = jsonencode([
    {
      name  = "worker"
      image = "${aws_ecr_repository.backend.repository_url}:latest"

      environment = [
        {
          name  = "SERVICE"
          value = "worker"  # Starts the worker, not the uvicorn server
        },
        {
          name  = "NUM_WORKERS"
          value = tostring(var.ecs_num_workers)
        },
        {
          name  = "DEPLOYMENT_ID"
          value = var.deployment
        },
        {
          name  = "LLM_CACHE_PATH"
          value = ""  # Disable cache
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
          name  = "DOCENT_PG_PASSWORD"
          value = var.db_password
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
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs.name
          awslogs-region        = var.aws_region
          awslogs-stream-prefix = "worker"
        }
      }

      essential = true
    }
  ])

  tags = {
    Name        = "${var.project_name}-${var.deployment}-worker-task"
    Deployment = var.deployment
  }
}

resource "aws_ecs_service" "worker" {
  name            = "${var.project_name}-${var.deployment}-worker"
  cluster         = aws_ecs_cluster.main.id
  task_definition = aws_ecs_task_definition.worker.arn
  desired_count   = var.ecs_desired_count
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = aws_subnet.private[*].id
    security_groups  = [aws_security_group.ecs_tasks.id]
    assign_public_ip = false
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-worker-service"
    Deployment = var.deployment
  }
}

resource "aws_appautoscaling_target" "ecs_worker" {
  max_capacity       = var.ecs_max_size
  min_capacity       = var.ecs_min_size
  resource_id        = "service/${aws_ecs_cluster.main.name}/${aws_ecs_service.worker.name}"
  scalable_dimension = "ecs:service:DesiredCount"
  service_namespace  = "ecs"

  tags = {
    Name        = "${var.project_name}-${var.deployment}-worker-autoscaling-target"
    Deployment = var.deployment
  }
}

resource "aws_appautoscaling_policy" "ecs_worker_cpu" {
  name               = "${var.project_name}-${var.deployment}-worker-cpu-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs_worker.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs_worker.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs_worker.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageCPUUtilization"
    }
    target_value = 50.0
  }
}

resource "aws_appautoscaling_policy" "ecs_worker_memory" {
  name               = "${var.project_name}-${var.deployment}-worker-memory-scaling"
  policy_type        = "TargetTrackingScaling"
  resource_id        = aws_appautoscaling_target.ecs_worker.resource_id
  scalable_dimension = aws_appautoscaling_target.ecs_worker.scalable_dimension
  service_namespace  = aws_appautoscaling_target.ecs_worker.service_namespace

  target_tracking_scaling_policy_configuration {
    predefined_metric_specification {
      predefined_metric_type = "ECSServiceAverageMemoryUtilization"
    }
    target_value = 50.0
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
          value = ""  # Disable cache
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
          name  = "DOCENT_PG_PASSWORD"
          value = var.db_password
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
