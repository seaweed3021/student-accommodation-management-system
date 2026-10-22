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
