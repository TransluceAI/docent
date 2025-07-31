# Tailscale private access configuration (METR deployment only)
# This file contains all Tailscale-related resources that enable private-only access
# to the App Runner API service through a Tailscale subnet router.

locals {
  enable_tailscale = var.deployment == "metr"
  tailscale_cidr   = "100.64.0.0/10"  # Tailscale CGNAT range
}

# Data source to get the latest Amazon Linux 2023 AMI
data "aws_ami" "amazon_linux" {
  count = local.enable_tailscale ? 1 : 0

  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-*-x86_64"]
  }

  filter {
    name   = "virtualization-type"
    values = ["hvm"]
  }
}

# Security group for Tailscale subnet router
resource "aws_security_group" "tailscale_router" {
  count = local.enable_tailscale ? 1 : 0

  name_prefix = "${var.project_name}-${var.deployment}-tailscale-router-"
  vpc_id      = aws_vpc.main.id

  # Allow Tailscale traffic (UDP 41641)
  ingress {
    from_port   = 41641
    to_port     = 41641
    protocol    = "udp"
    cidr_blocks = ["0.0.0.0/0"]
    description = "Tailscale WireGuard"
  }

  # Allow SSH from Tailscale network for management
  ingress {
    from_port   = 22
    to_port     = 22
    protocol    = "tcp"
    cidr_blocks = [local.tailscale_cidr]
    description = "SSH from Tailscale network"
  }

  # Allow all outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-tailscale-router-sg"
    Deployment = var.deployment
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Security group for VPC endpoint (App Runner private access)
resource "aws_security_group" "app_runner_vpc_endpoint" {
  count = local.enable_tailscale ? 1 : 0

  name_prefix = "${var.project_name}-${var.deployment}-apprunner-endpoint-"
  vpc_id      = aws_vpc.main.id

  # Allow HTTPS traffic from VPC CIDR (routed through Tailscale subnet router)
  ingress {
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = [aws_vpc.main.cidr_block]
    description = "HTTPS from VPC via Tailscale subnet router"
  }

  # Allow all outbound traffic
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-apprunner-endpoint-sg"
    Deployment = var.deployment
  }

  lifecycle {
    create_before_destroy = true
  }
}

# IAM role for Tailscale subnet router EC2 instance
resource "aws_iam_role" "tailscale_router" {
  count = local.enable_tailscale ? 1 : 0

  name = "${var.project_name}-${var.deployment}-tailscale-router-role"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Action = "sts:AssumeRole"
        Effect = "Allow"
        Principal = {
          Service = "ec2.amazonaws.com"
        }
      }
    ]
  })

  tags = {
    Name        = "${var.project_name}-${var.deployment}-tailscale-router-role"
    Deployment = var.deployment
  }
}

# IAM instance profile for Tailscale subnet router
resource "aws_iam_instance_profile" "tailscale_router" {
  count = local.enable_tailscale ? 1 : 0

  name = "${var.project_name}-${var.deployment}-tailscale-router-profile"
  role = aws_iam_role.tailscale_router[0].name

  tags = {
    Name        = "${var.project_name}-${var.deployment}-tailscale-router-profile"
    Deployment = var.deployment
  }
}

# Launch template for Tailscale subnet router
resource "aws_launch_template" "tailscale_router" {
  count = local.enable_tailscale ? 1 : 0

  name_prefix   = "${var.project_name}-${var.deployment}-tailscale-router-"
  image_id      = data.aws_ami.amazon_linux[0].id
  instance_type = "t3.micro"

  vpc_security_group_ids = [aws_security_group.tailscale_router[0].id]

  iam_instance_profile {
    name = aws_iam_instance_profile.tailscale_router[0].name
  }

  user_data = base64encode(templatefile("${path.module}/tailscale-user-data.tftpl", {
    vpc_cidr           = aws_vpc.main.cidr_block
    tailscale_auth_key = var.tailscale_auth_key
  }))

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name        = "${var.project_name}-${var.deployment}-tailscale-router"
      Deployment = var.deployment
      Role        = "tailscale-subnet-router"
    }
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-tailscale-router-lt"
    Deployment = var.deployment
  }

  lifecycle {
    create_before_destroy = true
  }
}

# Auto Scaling Group for Tailscale subnet router (for high availability)
resource "aws_autoscaling_group" "tailscale_router" {
  count = local.enable_tailscale ? 1 : 0

  name                = "${var.project_name}-${var.deployment}-tailscale-router-asg"
  vpc_zone_identifier = aws_subnet.public[*].id
  target_group_arns   = []
  health_check_type   = "EC2"
  health_check_grace_period = 300

  min_size         = 1
  max_size         = 2
  desired_capacity = 1

  launch_template {
    id      = aws_launch_template.tailscale_router[0].id
    version = "$Latest"
  }

  tag {
    key                 = "Name"
    value               = "${var.project_name}-${var.deployment}-tailscale-router-asg"
    propagate_at_launch = false
  }

  tag {
    key                 = "Deployment"
    value               = var.deployment
    propagate_at_launch = true
  }

  lifecycle {
    create_before_destroy = true
  }
}

# VPC Endpoint for App Runner
resource "aws_vpc_endpoint" "app_runner" {
  count = local.enable_tailscale ? 1 : 0

  vpc_id              = aws_vpc.main.id
  service_name        = "com.amazonaws.${var.aws_region}.apprunner.requests"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = aws_subnet.private[*].id
  security_group_ids  = [aws_security_group.app_runner_vpc_endpoint[0].id]

  private_dns_enabled = false

  tags = {
    Name        = "${var.project_name}-${var.deployment}-apprunner-vpc-endpoint"
    Deployment = var.deployment
  }
}

# VPC Ingress Connection for App Runner
resource "aws_apprunner_vpc_ingress_connection" "main" {
  count = local.enable_tailscale ? 1 : 0

  name        = "${var.project_name}-${var.deployment}-private-ingress"
  service_arn = aws_apprunner_service.api.arn

  ingress_vpc_configuration {
    vpc_id          = aws_vpc.main.id
    vpc_endpoint_id = aws_vpc_endpoint.app_runner[0].id
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-private-ingress"
    Deployment = var.deployment
  }
}

resource "aws_apprunner_vpc_ingress_connection" "frontend" {
  count = local.enable_tailscale && var.enable_frontend_app_runner ? 1 : 0

  name        = "${var.project_name}-${var.deployment}-frontend-private-ingress"
  service_arn = aws_apprunner_service.frontend[0].arn

  ingress_vpc_configuration {
    vpc_id          = aws_vpc.main.id
    vpc_endpoint_id = aws_vpc_endpoint.app_runner[0].id
  }

  tags = {
    Name        = "${var.project_name}-${var.deployment}-frontend-private-ingress"
    Deployment  = var.deployment
  }
}
