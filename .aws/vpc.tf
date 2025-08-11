resource "aws_vpc" "main" {
  cidr_block           = var.vpc_cidr_block
  enable_dns_hostnames = true
  enable_dns_support   = true

  tags = {
    Name       = "${var.project_name}-${var.deployment}-vpc"
    Deployment = var.deployment
  }
}

resource "aws_internet_gateway" "main" {
  vpc_id = aws_vpc.main.id

  tags = {
    Name       = "${var.project_name}-${var.deployment}-igw"
    Deployment = var.deployment
  }
}

resource "aws_subnet" "public" {
  count = var.public_subnet_count

  vpc_id                  = aws_vpc.main.id
  cidr_block              = cidrsubnet(var.vpc_cidr_block, 8, count.index + 1)
  availability_zone       = data.aws_availability_zones.available.names[count.index % length(data.aws_availability_zones.available.names)]
  map_public_ip_on_launch = true

  tags = {
    Name       = "${var.project_name}-${var.deployment}-public-subnet-${count.index + 1}"
    Deployment = var.deployment
    Type       = "Public"
  }
}

resource "aws_subnet" "private" {
  count = var.private_subnet_count

  vpc_id            = aws_vpc.main.id
  cidr_block        = cidrsubnet(var.vpc_cidr_block, 8, count.index + 10)
  availability_zone = data.aws_availability_zones.available.names[count.index % length(data.aws_availability_zones.available.names)]

  tags = {
    Name       = "${var.project_name}-${var.deployment}-private-subnet-${count.index + 1}"
    Deployment = var.deployment
    Type       = "Private"
  }
}

resource "aws_eip" "nat" {
  count = var.nat_gateway_count

  domain     = "vpc"
  depends_on = [aws_internet_gateway.main]

  tags = {
    Name       = "${var.project_name}-${var.deployment}-nat-eip-${count.index + 1}"
    Deployment = var.deployment
  }
}

resource "aws_nat_gateway" "main" {
  count = var.nat_gateway_count

  allocation_id = aws_eip.nat[count.index].id
  subnet_id     = aws_subnet.public[count.index].id

  tags = {
    Name       = "${var.project_name}-${var.deployment}-nat-gateway-${count.index + 1}"
    Deployment = var.deployment
  }

  depends_on = [aws_internet_gateway.main]
}

resource "aws_route_table" "public" {
  vpc_id = aws_vpc.main.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.main.id
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-public-rt"
    Deployment = var.deployment
  }
}

resource "aws_route_table" "private" {
  count = var.nat_gateway_count

  vpc_id = aws_vpc.main.id

  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.main[count.index].id
  }

  tags = {
    Name       = "${var.project_name}-${var.deployment}-private-rt-${count.index + 1}"
    Deployment = var.deployment
  }
}

resource "aws_route_table_association" "public" {
  count = var.public_subnet_count

  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public.id
}

resource "aws_route_table_association" "private" {
  count = var.private_subnet_count

  subnet_id      = aws_subnet.private[count.index].id
  # Distribute private subnets across available route tables (and thus NAT gateways)
  route_table_id = aws_route_table.private[count.index % length(aws_route_table.private)].id
}
