# Messaging + monitoring for RoomSphere.
# SNS topic for confirmation messages and alarms, reached from the private subnets
# through an interface VPC endpoint (there is no NAT gateway).

variable "notify_email" {
  description = "Email address subscribed to the notifications topic (must confirm the subscription email)"
  type        = string
  default     = ""
}

resource "aws_sns_topic" "notifications" {
  name = "roomsphere-notifications"
  tags = local.common_tags
}

resource "aws_sns_topic_subscription" "email" {
  count     = var.notify_email == "" ? 0 : 1
  topic_arn = aws_sns_topic.notifications.arn
  protocol  = "email"
  endpoint  = var.notify_email
}

# Lets the Lambdas in the private subnets call SNS without internet access.
resource "aws_security_group" "vpc_endpoints" {
  name        = "roomsphere-endpoints-sg"
  description = "HTTPS from the app security group to VPC interface endpoints"
  vpc_id      = data.aws_vpc.existing.id

  ingress {
    from_port       = 443
    to_port         = 443
    protocol        = "tcp"
    security_groups = [aws_security_group.app.id]
  }

  tags = merge(local.common_tags, { Name = "roomsphere-endpoints-sg" })
}

resource "aws_vpc_endpoint" "sns" {
  vpc_id              = data.aws_vpc.existing.id
  service_name        = "com.amazonaws.us-east-1.sns"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.private_a.id, aws_subnet.private_b.id]
  security_group_ids  = [aws_security_group.vpc_endpoints.id]
  private_dns_enabled = true

  tags = merge(local.common_tags, { Name = "roomsphere-sns-endpoint" })
}

# --- logs and alarms ---

# Lambda application logs
resource "aws_cloudwatch_log_group" "api" {
  name              = "/aws/lambda/${aws_lambda_function.api.function_name}"
  retention_in_days = 14
  tags              = local.common_tags
}

# API Gateway access logs
resource "aws_cloudwatch_log_group" "api_access" {
  name              = "/aws/apigateway/roomsphere-api-access"
  retention_in_days = 14
  tags              = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  alarm_name          = "roomsphere-api-errors"
  alarm_description   = "API Lambda returned errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.api.function_name }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.notifications.arn]
  tags                = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "roomsphere-api-5xx"
  alarm_description   = "API Gateway returned 5xx responses"
  namespace           = "AWS/ApiGateway"
  metric_name         = "5xx"
  dimensions          = { ApiId = aws_apigatewayv2_api.api.id }
  statistic           = "Sum"
  period              = 60
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.notifications.arn]
  tags                = local.common_tags
}

resource "aws_cloudwatch_metric_alarm" "rds_cpu" {
  alarm_name          = "roomsphere-rds-cpu-high"
  alarm_description   = "RDS CPU above 80% for 5 minutes"
  namespace           = "AWS/RDS"
  metric_name         = "CPUUtilization"
  dimensions          = { DBInstanceIdentifier = aws_db_instance.roomsphere.identifier }
  statistic           = "Average"
  period              = 300
  evaluation_periods  = 1
  threshold           = 80
  comparison_operator = "GreaterThanThreshold"
  alarm_actions       = [aws_sns_topic.notifications.arn]
  tags                = local.common_tags
}

output "notifications_topic_arn" {
  value = aws_sns_topic.notifications.arn
}
