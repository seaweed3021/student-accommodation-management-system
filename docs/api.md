# RoomSphere API

Python Lambda behind an API Gateway HTTP API. Code: `backend/handler.py`. Infrastructure: `infrastructure/terraform/api.tf`.

API Gateway checks the Cognito JWT on protected routes before the Lambda runs. The Lambda then checks the `cognito:groups` claim, so the landlord role has elevated access.

| Route | Auth | Who | What it does |
|---|---|---|---|
| GET /health | none | anyone | checks the database connection |
| GET /rooms | none | anyone | lists rooms with property and rent |
| GET /rooms/{id} | none | anyone | one room, 404 if missing |
| POST /applications | JWT | any signed-in customer (not in the landlord group) | creates an application (body: room_id, move_in_date, message). Creates the users row from the token on first use |
| GET /applications/mine | JWT | customer | the caller's own applications, with payment status. The landlord note is never returned |
| POST /applications/{id}/payment | JWT | customer who owns the application | mock deposit payment (body: card_last4). Only for approved applications. Marks the room occupied and creates the tenancy in one transaction. Card ending 0002 is declined (402). A second payment returns 409 |
| GET /applications | JWT | landlord group | lists all applications |
| PATCH /applications/{id} | JWT | landlord group | approve or reject (body: status, optional landlord_note). 409 if already decided or the room is taken |
| GET /dashboard | JWT | landlord group | live numbers: rooms by status, occupancy rate, applications by status, rent roll, deposits collected, recent applications |

Send the Cognito **ID token** as `Authorization: Bearer <token>` (the authorizer checks the `aud` claim, which only the ID token carries). Errors: 400 bad input, 402 card declined, 401 missing or invalid token (API Gateway), 403 wrong group, 404 not found, 409 conflict (already decided, already paid, room taken), 500 internal (detail goes to CloudWatch only).

## Messaging and payment
- **Messaging.** Approve, reject and payment publish a confirmation to the SNS topic `roomsphere-notifications` (email subscription set by the `notify_email` variable). The Lambda reaches SNS through an interface VPC endpoint because there is no NAT. A failed publish never fails the request; the response carries `notification_sent: true/false`.
- **Payment.** A mock provider stands in for a payment gateway sandbox: it validates the request, writes a `payments` row with a reference (`MOCK-...`) and stores no card data. Whether this counts as the "equivalent integration" is to be confirmed with the instructor.
- **Alarms.** CloudWatch alarms on Lambda errors, API Gateway 5xx and RDS CPU notify the same topic.

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
