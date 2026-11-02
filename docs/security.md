# RoomSphere security design

How identity, network exposure, secrets and IAM work today, and what we would change outside the AWS Learner Lab. See `docs/architecture-v1.png` for the diagram.

## 1. Identity and roles
- **Amazon Cognito user pool** handles sign up, email confirmation and sign in (front end: `frontend/auth.js`).
- **Landlord (owner)** is the Cognito group `landlord`. Only an administrator can add a user to a group, so a self-signed-up user cannot give themselves the role.
- **Customer (student)** is any signed-in user who is not in `landlord`. The front end sends landlords to `owner.html` and everyone else to `customer.html`.
- **API checks:** API Gateway validates the JWT (issuer and audience) on protected routes before the Lambda runs. The Lambda then checks the `cognito:groups` claim: `GET /applications` is landlord only, `POST /applications` is customers only.
- **Link to data:** the Cognito `sub` is stored in `users.cognito_sub`, so every application belongs to one login.

## 2. Network and exposure
| Component | Exposure | Protection |
|---|---|---|
| Front end (GitHub Pages) | Public, HTTPS | Static files only, no secrets |
| Cognito | Public | Managed by AWS, email confirmation |
| API Gateway | Public, HTTPS | JWT authorizer on protected routes, CORS limited to the Pages origin |
| Lambda | Private subnets | Reached only through API Gateway |
| RDS PostgreSQL | Private, `publicly_accessible = false` | Security group `roomsphere-db-sg` accepts port 5432 only from `roomsphere-app-sg` |
| S3 documents bucket | Private | Block Public Access on, encrypted (AES256), versioning on |

## 3. Secrets
- No AWS access keys are in the repository or in GitHub. The Pages deployment uses GitHub's built-in permissions only.
- The database password is a sensitive Terraform variable (`db_password`), never committed.
- Cognito pool and client IDs in `frontend/config.js` are public identifiers by design. They are not secrets.
- **Trade-off:** the Lambda receives the database password as an environment variable, because the private subnets have no route to the internet and so cannot reach Secrets Manager. Anyone who can read the function configuration can see it.

## 4. Encryption
- RDS storage is encrypted. S3 uses server-side encryption.
- Traffic from the browser to Pages, Cognito and API Gateway is HTTPS.

## 5. IAM
The Learner Lab does not allow creating IAM roles, so all Lambdas run as `LabRole`. That role is broader than needed. In a normal account each function would get its own role. The policy we would attach to the API function:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "Logs",
      "Effect": "Allow",
      "Action": ["logs:CreateLogGroup", "logs:CreateLogStream", "logs:PutLogEvents"],
      "Resource": "arn:aws:logs:us-east-1:*:log-group:/aws/lambda/roomsphere-api:*"
    },
    {
      "Sid": "VpcNetworking",
      "Effect": "Allow",
      "Action": ["ec2:CreateNetworkInterface", "ec2:DescribeNetworkInterfaces", "ec2:DeleteNetworkInterface"],
      "Resource": "*"
    },
    {
      "Sid": "DocumentsBucket",
      "Effect": "Allow",
      "Action": ["s3:GetObject", "s3:PutObject"],
      "Resource": "arn:aws:s3:::roomsphere-private-docs-rsm-7k29x/*"
    }
  ]
}
```

## 6. Known gaps
- All functions use `LabRole` (broad) because of the lab.
- The app and database security groups allow all outbound traffic.
- The application connects as the database admin user. It should use a limited user with only the rights it needs.
- The database password sits in a Lambda environment variable (see section 3).
- No throttling or WAF on the API yet.
- The database is single-AZ, with backups off and deletion protection off. This is acceptable for a development environment and should change for production.
