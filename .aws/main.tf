############################
# Networking
############################

resource "aws_vpc" "main" {
  cidr_block           = "10.0.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = { Name = "tf-demo-vpc" }
}

# Two public subnets in different AZs (required for RDS subnet group)
resource "aws_subnet" "public" {
  for_each = {
    b = "10.0.1.0/24"
    c = "10.0.2.0/24"
  }

  vpc_id                  = aws_vpc.main.id
  cidr_block              = each.value
  availability_zone       = "${var.aws_region}${each.key}"
  map_public_ip_on_launch = true

  tags = { Name = "tf-demo-public-${each.key}" }
}

resource "aws_internet_gateway" "gw" {
  vpc_id = aws_vpc.main.id
  tags   = { Name = "tf-demo-igw" }
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.gw.id
  }

  tags = { Name = "tf-demo-rt" }
}

resource "aws_route_table_association" "public" {
  for_each       = aws_subnet.public
  subnet_id      = each.value.id
  route_table_id = aws_route_table.public.id
}

############################
# Security groups
############################

resource "aws_security_group" "ec2_sg" {
  name        = "tf-demo-ec2-sg"
  description = "Inbound 22/80/443/7776 from anywhere; all egress"
  vpc_id      = aws_vpc.main.id

  ingress = [
    for port in [22, 80, 443, 7776] : {
      description      = "port ${port}"
      from_port        = port
      to_port          = port
      protocol         = "tcp"
      cidr_blocks      = ["0.0.0.0/0"]
      ipv6_cidr_blocks = []
      prefix_list_ids  = []
      security_groups  = []
      self             = false
    }
  ]

  egress = [{
    description      = "All outbound traffic"
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = []
    prefix_list_ids  = []
    security_groups  = []
    self             = false
  }]
}

resource "aws_security_group" "rds_sg" {
  name        = "tf-demo-rds-sg"
  description = "Allow Postgres only from EC2 SG"
  vpc_id      = aws_vpc.main.id

  ingress = [{
    description      = "Postgres from EC2"
    protocol         = "tcp"
    from_port        = 5432
    to_port          = 5432
    security_groups  = [aws_security_group.ec2_sg.id]
    cidr_blocks      = []
    ipv6_cidr_blocks = []
    prefix_list_ids  = []
    self             = false
  }]

  egress = [{
    description      = "All outbound traffic"
    from_port        = 0
    to_port          = 0
    protocol         = "-1"
    cidr_blocks      = ["0.0.0.0/0"]
    ipv6_cidr_blocks = []
    prefix_list_ids  = []
    security_groups  = []
    self             = false
  }]
}

############################
# EC2 instance
############################

# Grab latest Amazon Linux 2023 AMI in the chosen region
data "aws_ami" "amazon_linux" {
  most_recent = true
  owners      = ["amazon"]

  filter {
    name   = "name"
    values = ["al2023-ami-minimal-*x86_64*"]
  }
}

resource "aws_instance" "app" {
  ami                         = data.aws_ami.amazon_linux.id
  instance_type               = var.instance_type
  subnet_id                   = aws_subnet.public["b"].id
  vpc_security_group_ids      = [aws_security_group.ec2_sg.id]
  key_name                    = var.key_name
  associate_public_ip_address = true

  root_block_device {
    volume_size = var.root_volume_size
    volume_type = var.root_volume_type
    encrypted   = var.root_volume_encrypted
    delete_on_termination = true
  }

  tags = { Name = "tf-demo-app" }
}

############################
# RDS (PostgreSQL 15)
############################

# RDS needs at least two subnets in different AZs
resource "aws_db_subnet_group" "main" {
  name       = "tf-demo-dbsubnet"
  subnet_ids = [for s in aws_subnet.public : s.id]

  tags = { Name = "tf-demo-dbsubnet" }
}

resource "aws_db_instance" "postgres" {
  identifier              = "tf-demo-postgres"
  engine                  = "postgres"
  engine_version          = "15"
  instance_class          = var.db_instance_class
  allocated_storage       = var.db_allocated_storage
  username                = var.db_username
  password                = var.db_password
  db_subnet_group_name    = aws_db_subnet_group.main.name
  vpc_security_group_ids  = [aws_security_group.rds_sg.id]
  publicly_accessible     = false
  skip_final_snapshot     = true   # NOT for production!
  deletion_protection     = false  # NOT for production!
  auto_minor_version_upgrade = true

  tags = { Name = "tf-demo-postgres" }
}
