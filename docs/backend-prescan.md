# Backend code-quality pre-scan (local, before SonarQube)

Run on 2026-11-23 on `backend/handler.py`, `backend/local_server.py` and `backend/tests/`, using bandit (security), radon and pylint (complexity and code smells). This is a local approximation of what SonarQube reports. It does not replace the SonarQube scan, and the SonarQube results are recorded separately.

| Finding | Before | After |
|---|---|---|
| Request handler too complex (cognitive complexity 18, SonarQube limit 15) | `handler()` | route tables + `_dispatch()`, highest function is now 10 |
| Repeated string literals (`"status"` x8, `"error"` x25, `"approved"` x5, others) | 8 literals | named constants and an `_error()` helper |
| Silent `try/except/pass` around a rollback | 1 | the failure is logged |
| Unused function parameters | 3 | prefixed with `_` where the route table requires the signature |
| Files opened without an encoding | 2 | `encoding="utf-8"` |
| Password-like literal in the test file | 1 | read from `TEST_DB_PASSWORD` |
| Security findings (bandit) | 3 low | 0 |

Behaviour check: the 37 test responses in `docs/api-test-log.txt` are identical before and after the refactor.

## Known items to explain in the SonarQube report
- `backend/local_server.py` decodes the JWT payload without verifying the signature. This is deliberate and limited to development on localhost. On AWS, the API Gateway JWT authorizer verifies the token before the Lambda runs. The file is not deployed (`backend/build.sh` copies only `handler.py` and the SQL).
- `docker-compose.yml` and `local_server.py` use a throwaway local database password (`localdev-password`) for the Docker test database only. It is not used on AWS, where the password is supplied at deploy time and never stored in the repo.
- `except Exception` appears in the Lambda's last-resort handler and in the SNS publish. Both are intentional: the detail is logged to CloudWatch, the client gets a generic error, and a messaging failure must not fail the request.
