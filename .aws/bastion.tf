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
  key_name   = "${var.project_name}-${var.environment}-bastion-key"
  public_key = var.bastion_public_key

  tags = {
    Name        = "${var.project_name}-${var.environment}-bastion-key"
    Environment = var.environment
  }
}

resource "aws_instance" "bastion" {
  ami           = data.aws_ami.amazon_linux_2023.id
  instance_type = "t3.micro"

  key_name               = aws_key_pair.bastion.key_name
  vpc_security_group_ids = [aws_security_group.bastion.id]
  subnet_id              = aws_subnet.public[0].id

  tags = {
    Name        = "${var.project_name}-${var.environment}-bastion"
    Environment = var.environment
  }

  lifecycle {
    ignore_changes = [ami]
  }
}
