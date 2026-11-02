# RoomSphere API

Python Lambda behind an API Gateway HTTP API. Code: `backend/handler.py`. Infrastructure: `infrastructure/terraform/api.tf`.

API Gateway checks the Cognito JWT on protected routes before the Lambda runs. The Lambda then checks the `cognito:groups` claim, so the landlord role has elevated access.

| Route | Auth | Who | What it does |
|---|---|---|---|
| GET /health | none | anyone | checks the database connection |
| GET /rooms | none | anyone | lists rooms with property and rent |
| GET /rooms/{id} | none | anyone | one room, 404 if missing |
| POST /applications | JWT | student group | creates an application (body: room_id, move_in_date, message). Creates the users row from the token on first use |
| GET /applications | JWT | landlord group | lists all applications |

Errors: 400 bad input, 401 missing or invalid token (API Gateway), 403 wrong group, 404 not found, 500 internal (detail goes to CloudWatch only).

## Design notes
- The Lambda runs in the private subnets with the `app` security group, the only source the database security group accepts. There is no NAT, so the Lambda cannot reach the internet or Secrets Manager.
- Because of that, the database password is passed as a Lambda environment variable from the sensitive Terraform variable `db_password`. Trade-off: the value is visible to anyone who can read the function configuration. In an account that allows it, move it to Secrets Manager with a VPC endpoint.
- The Cognito subject (`sub`) links the login to the `users` table.
- `roomsphere-init-db` loads `db/schema.sql` once, and with `{"seed": true}` also `db/seed.sql`. It does nothing if the schema already exists.

## Deploy (needs the AWS Learner Lab account that owns the infrastructure)
1. `bash backend/build.sh`
2. `cd infrastructure/terraform`, then `terraform init`, `terraform plan`, `terraform apply` (the lock file will gain the archive provider; commit it)
3. In the Lambda console, test `roomsphere-init-db` with `{"seed": true}`
4. Open `<api_url>/rooms` in a browser
