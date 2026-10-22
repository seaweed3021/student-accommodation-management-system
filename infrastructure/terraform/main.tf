terraform {
  required_version = ">= 1.5.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"
}

locals {
  project = "RoomSphere"
  common_tags = {
    Project     = "RoomSphere"
    Environment = "Development"
    ManagedBy   = "Terraform"
  }
}

data "aws_vpc" "existing" {
  id = "vpc-04321d6d5be461960"
}

resource "aws_subnet" "private_a" {
  vpc_id                  = data.aws_vpc.existing.id
  cidr_block              = "172.31.96.0/24"
  availability_zone       = "us-east-1a"
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "roomsphere-private-a"
  })
}

resource "aws_subnet" "private_b" {
  vpc_id                  = data.aws_vpc.existing.id
  cidr_block              = "172.31.97.0/24"
  availability_zone       = "us-east-1b"
  map_public_ip_on_launch = false

  tags = merge(local.common_tags, {
    Name = "roomsphere-private-b"
  })
}

resource "aws_route_table" "private" {
  vpc_id = data.aws_vpc.existing.id

  tags = merge(local.common_tags, {
    Name = "roomsphere-private-rt"
  })
}

resource "aws_route_table_association" "private_a" {
  subnet_id      = aws_subnet.private_a.id
  route_table_id = aws_route_table.private.id
}

resource "aws_route_table_association" "private_b" {
  subnet_id      = aws_subnet.private_b.id
  route_table_id = aws_route_table.private.id
}

resource "aws_db_subnet_group" "roomsphere" {
  name        = "roomsphere-db-subnets"
  description = "Private subnet group for RoomSphere RDS"

  subnet_ids = [
    aws_subnet.private_a.id,
    aws_subnet.private_b.id
  ]

  tags = local.common_tags
}


resource "aws_security_group" "app" {
  name        = "roomsphere-app-sg"
  description = "Security group for RoomSphere application"
  vpc_id      = data.aws_vpc.existing.id

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "roomsphere-app-sg"
  })
}

resource "aws_security_group" "db" {
  name        = "roomsphere-db-sg"
  description = "Allow PostgreSQL only from RoomSphere application"
  vpc_id      = data.aws_vpc.existing.id

  ingress {
    description     = "PostgreSQL from RoomSphere application"
    from_port       = 5432
    to_port         = 5432
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = merge(local.common_tags, {
    Name = "roomsphere-db-sg"
  })
}

output "vpc_id" {
  value = data.aws_vpc.existing.id
}

output "private_subnet_ids" {
  value = [
    aws_subnet.private_a.id,
    aws_subnet.private_b.id
  ]
}

output "rds_subnet_group_name" {
  value = aws_db_subnet_group.roomsphere.name
}

resource "aws_s3_bucket_public_access_block" "private_documents" {
  bucket = "roomsphere-private-docs-rsm-7k29x"

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "private_documents" {
  bucket = "roomsphere-private-docs-rsm-7k29x"

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_versioning" "private_documents" {
  bucket = "roomsphere-private-docs-rsm-7k29x"

  versioning_configuration {
    status = "Enabled"
  }
}

output "private_documents_bucket_name" {
  description = "Private S3 bucket for RoomSphere documents"
  value       = "roomsphere-private-docs-rsm-7k29x"
}


variable "db_password" {
  description = "Master password for the RoomSphere development database"
  type        = string
  sensitive   = true
  nullable    = false

  validation {
    condition     = length(var.db_password) >= 12
    error_message = "The database password must be at least 12 characters."
  }
}

resource "aws_db_instance" "roomsphere" {
  identifier        = "roomsphere-postgres-dev"
  engine            = "postgres"
  instance_class    = "db.t3.micro"
  allocated_storage = 20
  storage_type      = "gp3"

  db_name  = "roomsphere"
  username = "roomsphere_admin"
  password = var.db_password

  db_subnet_group_name   = aws_db_subnet_group.roomsphere.name
  vpc_security_group_ids = [aws_security_group.db.id]
  publicly_accessible    = false

  storage_encrypted          = true
  backup_retention_period    = 0
  auto_minor_version_upgrade = true
  apply_immediately          = true

  skip_final_snapshot = true
  deletion_protection = false

  tags = merge(local.common_tags, {
    Name = "roomsphere-postgres-dev"
  })
}

output "rds_endpoint" {
  description = "Private endpoint for the RoomSphere PostgreSQL database"
  value       = aws_db_instance.roomsphere.endpoint
}

output "rds_database_name" {
  value = aws_db_instance.roomsphere.db_name
}

