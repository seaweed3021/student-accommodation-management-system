# RoomSphere API: Lambda + API Gateway HTTP API with a Cognito JWT authorizer.
# Uses LabRole because the Learner Lab does not allow creating IAM roles.
# Build the package first:  bash backend/build.sh

variable "cognito_user_pool_id" {
  description = "Existing Cognito user pool (created by hand in the console)"
  type        = string
  default     = "us-east-1_Kb4KJhT3X"
}

variable "cognito_client_id" {
  description = "Cognito app client used by the front end"
  type        = string
  default     = "2fpqung9sp8v1n786fveo3g882"
}

variable "frontend_origin" {
  description = "Origin allowed by CORS"
  type        = string
  default     = "https://seaweed3021.github.io"
}

data "aws_iam_role" "lab" {
  name = "LabRole"
}

data "archive_file" "api" {
  type        = "zip"
  source_dir  = "${path.module}/../../backend/build"
  output_path = "${path.module}/api.zip"
}

locals {
  api_env = {
    DB_HOST     = aws_db_instance.roomsphere.address
    DB_NAME     = aws_db_instance.roomsphere.db_name
    DB_USER     = aws_db_instance.roomsphere.username
    DB_PASSWORD = var.db_password
  }
}

resource "aws_lambda_function" "api" {
  function_name    = "roomsphere-api"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "handler.handler"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  timeout          = 10
  memory_size      = 256

  vpc_config {
    subnet_ids         = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    security_group_ids = [aws_security_group.app.id]
  }

  environment {
    variables = local.api_env
  }

  tags = local.common_tags
}

# One-time schema loader. Invoke from the console with {"seed": true} for demo rooms.
resource "aws_lambda_function" "init_db" {
  function_name    = "roomsphere-init-db"
  role             = data.aws_iam_role.lab.arn
  runtime          = "python3.12"
  handler          = "handler.init_handler"
  filename         = data.archive_file.api.output_path
  source_code_hash = data.archive_file.api.output_base64sha256
  timeout          = 30
  memory_size      = 256

  vpc_config {
    subnet_ids         = [aws_subnet.private_a.id, aws_subnet.private_b.id]
    security_group_ids = [aws_security_group.app.id]
  }

  environment {
    variables = local.api_env
  }

  tags = local.common_tags
}

resource "aws_apigatewayv2_api" "api" {
  name          = "roomsphere-api"
  protocol_type = "HTTP"

  cors_configuration {
    allow_origins = [var.frontend_origin]
    allow_methods = ["GET", "POST", "OPTIONS"]
    allow_headers = ["authorization", "content-type"]
  }

  tags = local.common_tags
}

resource "aws_apigatewayv2_authorizer" "cognito" {
  api_id           = aws_apigatewayv2_api.api.id
  name             = "cognito-jwt"
  authorizer_type  = "JWT"
  identity_sources = ["$request.header.Authorization"]

  jwt_configuration {
    issuer   = "https://cognito-idp.us-east-1.amazonaws.com/${var.cognito_user_pool_id}"
    audience = [var.cognito_client_id]
  }
}

resource "aws_apigatewayv2_integration" "lambda" {
  api_id                 = aws_apigatewayv2_api.api.id
  integration_type       = "AWS_PROXY"
  integration_uri        = aws_lambda_function.api.invoke_arn
  payload_format_version = "2.0"
}

locals {
  public_routes    = ["GET /health", "GET /rooms", "GET /rooms/{id}"]
  protected_routes = ["POST /applications", "GET /applications"]
}

resource "aws_apigatewayv2_route" "public" {
  for_each  = toset(local.public_routes)
  api_id    = aws_apigatewayv2_api.api.id
  route_key = each.value
  target    = "integrations/${aws_apigatewayv2_integration.lambda.id}"
}

resource "aws_apigatewayv2_route" "protected" {
  for_each           = toset(local.protected_routes)
  api_id             = aws_apigatewayv2_api.api.id
  route_key          = each.value
  target             = "integrations/${aws_apigatewayv2_integration.lambda.id}"
  authorization_type = "JWT"
  authorizer_id      = aws_apigatewayv2_authorizer.cognito.id
}

resource "aws_apigatewayv2_stage" "default" {
  api_id      = aws_apigatewayv2_api.api.id
  name        = "$default"
  auto_deploy = true
  tags        = local.common_tags
}

resource "aws_lambda_permission" "apigw" {
  statement_id  = "AllowApiGatewayInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.api.function_name
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_apigatewayv2_api.api.execution_arn}/*/*"
}

output "api_url" {
  value = aws_apigatewayv2_api.api.api_endpoint
}
