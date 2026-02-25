data "aws_ami" "amazon_linux_2023" {
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

resource "aws_key_pair" "bastion" {
  key_name   = "${var.project_name}-${var.deployment}-bastion-key"
  public_key = var.bastion_public_key

  tags = {
    Name       = "${var.project_name}-${var.deployment}-bastion-key"
    Deployment = var.deployment
  }
}

# IAM role for bastion to read SSM parameters
resource "aws_iam_role" "bastion" {
  name = "${var.project_name}-${var.deployment}-bastion-role"

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
    Name       = "${var.project_name}-${var.deployment}-bastion-role"
    Deployment = var.deployment
  }
}

resource "aws_iam_role_policy" "bastion_ssm" {
  name = "${var.project_name}-${var.deployment}-bastion-ssm"
  role = aws_iam_role.bastion.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid    = "ReadSSMParameters"
        Effect = "Allow"
        Action = [
          "ssm:GetParameter"
        ]
        Resource = [
          aws_ssm_parameter.tailscale_auth_key.arn,
          aws_ssm_parameter.tailscale_oauth_client_id.arn,
          aws_ssm_parameter.tailscale_oauth_client_secret.arn,
        ]
      },
      {
        Sid    = "DecryptSSM"
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

resource "aws_iam_instance_profile" "bastion" {
  name = "${var.project_name}-${var.deployment}-bastion-profile"
  role = aws_iam_role.bastion.name

  tags = {
    Name       = "${var.project_name}-${var.deployment}-bastion-profile"
    Deployment = var.deployment
  }
}

# Launch template for bastion with Tailscale
resource "aws_launch_template" "bastion" {
  name_prefix = "${var.project_name}-${var.deployment}-bastion-"
  key_name    = aws_key_pair.bastion.key_name

  image_id      = data.aws_ami.amazon_linux_2023.id
  instance_type = "t3.micro"

  vpc_security_group_ids = [aws_security_group.bastion.id]

  iam_instance_profile {
    name = aws_iam_instance_profile.bastion.name
  }

  user_data = base64encode(templatefile("${path.module}/tailscale-user-data.tftpl", {
    ssm_parameter_name                     = aws_ssm_parameter.tailscale_auth_key.name
    ssm_oauth_client_id_parameter_name     = aws_ssm_parameter.tailscale_oauth_client_id.name
    ssm_oauth_client_secret_parameter_name = aws_ssm_parameter.tailscale_oauth_client_secret.name
    aws_region                             = var.aws_region
    deployment                             = var.deployment
  }))

  tag_specifications {
    resource_type = "instance"
    tags = {
      Name       = "${var.project_name}-${var.deployment}-bastion"
      Deployment = var.deployment
      Role       = "bastion"
    }
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-bastion-lt"
    Deployment = var.deployment
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_instance" "bastion" {
  subnet_id = aws_subnet.public[0].id

  launch_template {
    id      = aws_launch_template.bastion.id
    version = "$Latest"
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-bastion"
    Deployment = var.deployment
    Role       = "bastion"
  }
}

# The bastion isn't part of the application, so it wouldn't get overloaded by high traffic the way the db/API/worker would.
# However, Vanta wants to see CPU monitoring on every EC2 instance.
resource "aws_cloudwatch_metric_alarm" "bastion_cpu_utilization" {
  count = var.rds_alarm_sns_topic_arn != "" ? 1 : 0

  alarm_name          = "${var.project_name}-${var.deployment}-bastion-cpu-high"
  comparison_operator = "GreaterThanThreshold"
  evaluation_periods  = 2
  metric_name         = "CPUUtilization"
  namespace           = "AWS/EC2"
  period              = 300
  statistic           = "Average"
  threshold           = 80
  alarm_description   = "Bastion CPU utilization exceeds 80%"

  dimensions = {
    InstanceId = aws_instance.bastion.id
  }

  alarm_actions = [var.rds_alarm_sns_topic_arn]
  ok_actions    = [var.rds_alarm_sns_topic_arn]

  tags = {
    Deployment = var.deployment
  }
}
