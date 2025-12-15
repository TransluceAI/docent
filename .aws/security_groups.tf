resource "aws_security_group" "rds" {
  name_prefix = "${var.project_name}-${var.deployment}-rds-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app_runner.id, aws_security_group.ecs_tasks.id, aws_security_group.bastion.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-rds-sg"
    Deployment = var.deployment
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "elasticache" {
  name_prefix = "${var.project_name}-${var.deployment}-elasticache-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 6379
    to_port         = 6379
    protocol        = "tcp"
    security_groups = [aws_security_group.app_runner.id, aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-elasticache-sg"
    Deployment = var.deployment
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "app_runner" {
  name_prefix = "${var.project_name}-${var.deployment}-app-runner-"
  vpc_id      = aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-app-runner-sg"
    Deployment = var.deployment
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "ecs_tasks" {
  name_prefix = "${var.project_name}-${var.deployment}-ecs-tasks-"
  vpc_id      = aws_vpc.main.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-ecs-tasks-sg"
    Deployment = var.deployment
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "datadog_agent" {
  name_prefix = "${var.project_name}-${var.deployment}-datadog-agent-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port   = 8126
    to_port     = 8126
    protocol    = "tcp"
    cidr_blocks = [var.vpc_cidr_block]
    description = "Allow APM traffic from within the VPC"
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-datadog-agent-sg"
    Deployment = var.deployment
    Role        = "datadog-agent"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_security_group" "vpc_endpoints" {
  name_prefix = "${var.project_name}-${var.deployment}-vpc-endpoints-"
  vpc_id      = aws_vpc.main.id

  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.app_runner.id, aws_security_group.ecs_tasks.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-vpc-endpoints-sg"
    Deployment = var.deployment
  }

  lifecycle {
    create_before_destroy = true
  }
}

# https://tailscale.com/kb/1082/firewall-ports
# This article describes how to configure relevant firewall ports for Tailscale.
resource "aws_security_group" "bastion" {
  name_prefix = "${var.project_name}-${var.deployment}-bastion-"
  vpc_id      = aws_vpc.main.id

  # Allow Tailscale traffic (UDP 41641)
  ingress {
    from_port   = 41641
    to_port     = 41641
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Tailscale WireGuard"
  }

  # Allow SSH only from Tailscale network
  # https://tailscale.com/kb/1304/ip-pool
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = ["100.64.0.0/10"] # Tailscale CGNAT range
    description = "SSH access from Tailscale network only"
  }

  # Permissive egress rules for all outbound traffic.
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-bastion-sg"
    Deployment = var.deployment
  }

  lifecycle {
    create_before_destroy = true
  }
}
