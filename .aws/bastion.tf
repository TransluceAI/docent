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

# Launch template for bastion with Tailscale
resource "aws_launch_template" "bastion" {
  name_prefix   = "${var.project_name}-${var.deployment}-bastion-"
  key_name      = aws_key_pair.bastion.key_name

  image_id      = data.aws_ami.amazon_linux_2023.id
  instance_type = "t3.micro"

  vpc_security_group_ids = [aws_security_group.bastion.id]

  user_data = base64encode(templatefile("${path.module}/tailscale-user-data.tftpl", {
    tailscale_auth_key = local.tailscale_auth_key
    deployment         = var.deployment
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
    precondition {
      condition     = length(trimspace(local.tailscale_auth_key)) > 0
      error_message = "Tailscale: set non-empty tailscale_auth_key. Provide via TF_VAR_tailscale_auth_key or a secrets tfvars file."
    }
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
  }
}
