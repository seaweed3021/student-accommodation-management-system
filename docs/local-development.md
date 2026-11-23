# Run the API locally

Use this to build and test the front end without waiting for the AWS deployment, and to save Learner Lab credits. It runs the same `backend/handler.py` as the Lambda. The final demo still runs on AWS.

## Start it (Docker Desktop and Python needed)
```powershell
docker compose up -d db                  # Postgres 16, schema + 3 demo rooms loaded on first start
pip install pg8000==1.31.2
python backend/local_server.py           # http://localhost:8000
```
Check: open http://localhost:8000/rooms. Reset the data with `docker compose down -v` then `docker compose up -d db`.

## Point the front end at it
Use `http://localhost:8000` as the API base URL while developing, and the `api_url` Terraform output once AWS is live. Serve the front end from `http://localhost:5500` (for example the VS Code Live Server extension) so CORS matches. The Cognito sign-in is the real one, and the ID token goes in `Authorization: Bearer <token>` exactly as on AWS.

## What differs from AWS
| | Local | AWS |
|---|---|---|
| Token check | payload decoded, signature **not** verified | API Gateway JWT authorizer verifies it |
| Messages | printed in the server console | published to SNS |
| Database | Docker Postgres | private RDS in the VPC |
| Landlord login | the token's `cognito:groups` must contain `landlord` | same |

Never expose this server beyond your own computer.
