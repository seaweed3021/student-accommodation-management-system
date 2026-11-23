"""Local test of backend/handler.py against Postgres 16 with simulated API Gateway events.

Setup: a throwaway Postgres on port 5433 with trust auth and an empty database named roomsphere
(for example a postgres:16 container, -p 5433:5432). Copy db/schema.sql and db/seed.sql next to
handler.py, then:  pip install pg8000==1.31.2  and  python backend/tests/test_api.py
The SNS client is faked. Remove the copied .sql files afterwards (backend/build.sh does the copy for deploys).
"""
import json, os, sys
os.environ.update(DB_HOST="127.0.0.1", DB_PORT=os.environ.get("TEST_DB_PORT", "5433"), DB_NAME="roomsphere", DB_USER="postgres", DB_PASSWORD=os.environ.get("TEST_DB_PASSWORD", ""), TOPIC_ARN="arn:aws:sns:us-east-1:000000000000:fake")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import handler as h

class FakeSNS:
    def __init__(self): self.sent = []; self.fail = False
    def publish(self, **kw):
        if self.fail: raise RuntimeError("endpoint unreachable")
        self.sent.append(kw)
sns = FakeSNS(); h._sns_client = sns

def ev(route, sub=None, groups=None, body=None, pid=None):
    claims = {}
    if sub: claims = {"sub": sub, "email": sub + "@x.com"}
    if groups: claims["cognito:groups"] = groups
    e = {"routeKey": route, "requestContext": {"authorizer": {"jwt": {"claims": claims}}}}
    if body is not None: e["body"] = json.dumps(body)
    if pid is not None: e["pathParameters"] = {"id": str(pid)}
    return e

fails = 0
def t(name, event, want, check=None):
    global fails
    r = h.handler(event, None); b = json.loads(r["body"])
    ok = r["statusCode"] == want and (check is None or check(b))
    fails += (not ok)
    print("%-44s %d %s%s" % (name, r["statusCode"], json.dumps(b)[:110], "" if ok else "   <-- FAIL (want %d)" % want))
    return b

print(h.init_handler({"seed": True}, None))
L = dict(sub="seed-landlord", groups="landlord")
S1 = dict(sub="stu1"); S2 = dict(sub="stu2")

t("GET /health", ev("GET /health"), 200)
t("GET /rooms (public)", ev("GET /rooms"), 200, lambda b: len(b) == 3)
t("dashboard, no token", ev("GET /dashboard"), 401)
t("dashboard, student", ev("GET /dashboard", **S1), 403)
t("dashboard, landlord (empty)", ev("GET /dashboard", **L), 200, lambda b: b["applications"]["total"] == 0 and b["rooms"]["total"] == 3)
a1 = t("S1 applies room 1", ev("POST /applications", body={"room_id": 1, "move_in_date": "2026-12-01"}, **S1), 201)["application_id"]
a2 = t("S2 applies room 1", ev("POST /applications", body={"room_id": 1, "move_in_date": "2026-12-01"}, **S2), 201)["application_id"]
t("my applications S1 (own only)", ev("GET /applications/mine", **S1), 200, lambda b: [x["application_id"] for x in b] == [a1])
t("my applications, landlord", ev("GET /applications/mine", **L), 403)
t("my applications, no token", ev("GET /applications/mine"), 401)
t("dashboard: 2 pending", ev("GET /dashboard", **L), 200, lambda b: b["applications"]["pending"] == 2)
t("PATCH by student", ev("PATCH /applications/{id}", pid=a1, body={"status": "approved"}, **S1), 403)
t("PATCH bad status", ev("PATCH /applications/{id}", pid=a1, body={"status": "maybe"}, **L), 400)
t("PATCH missing status", ev("PATCH /applications/{id}", pid=a1, body={}, **L), 400)
t("PATCH bad id", ev("PATCH /applications/{id}", pid="abc", body={"status": "approved"}, **L), 400)
t("PATCH unknown app", ev("PATCH /applications/{id}", pid=999, body={"status": "approved"}, **L), 404)
n = len(sns.sent)
t("approve S1", ev("PATCH /applications/{id}", pid=a1, body={"status": "approved", "landlord_note": "good ref"}, **L), 200, lambda b: b["status"] == "approved" and b["notification_sent"])
if len(sns.sent) != n + 1:
    raise SystemExit("SNS publish expected")
t("approve S1 again (double decision)", ev("PATCH /applications/{id}", pid=a1, body={"status": "rejected"}, **L), 409)
t("pay before approval (S2)", ev("POST /applications/{id}/payment", pid=a2, body={}, **S2), 409)
t("S2 cannot pay S1's application", ev("POST /applications/{id}/payment", pid=a1, body={}, **S2), 404)
t("landlord cannot pay", ev("POST /applications/{id}/payment", pid=a1, body={}, **L), 403)
t("pay bad card_last4", ev("POST /applications/{id}/payment", pid=a1, body={"card_last4": "12"}, **S1), 400)
t("pay declined card 0002", ev("POST /applications/{id}/payment", pid=a1, body={"card_last4": "0002"}, **S1), 402)
t("my apps: still no payment", ev("GET /applications/mine", **S1), 200, lambda b: b[0]["payment_status"] is None)
pay = t("pay OK", ev("POST /applications/{id}/payment", pid=a1, body={"card_last4": "4242"}, **S1), 201, lambda b: b["payment_reference"].startswith("MOCK-"))
t("pay twice", ev("POST /applications/{id}/payment", pid=a1, body={}, **S1), 409)
t("room 1 now occupied", ev("GET /rooms/{id}", pid=1), 200, lambda b: b["status"] == "occupied")
t("approve S2 for taken room", ev("PATCH /applications/{id}", pid=a2, body={"status": "approved"}, **L), 409)
t("reject S2", ev("PATCH /applications/{id}", pid=a2, body={"status": "rejected"}, **L), 200)
t("my apps S1 shows payment, hides note", ev("GET /applications/mine", **S1), 200, lambda b: b[0]["payment_status"] == "paid" and "landlord_note" not in b[0])
t("dashboard after flow", ev("GET /dashboard", **L), 200, lambda b: b["rooms"]["occupied"] == 2 and b["applications"]["approved"] == 1 and b["applications"]["rejected"] == 1 and b["deposits_collected"] == 850 and b["payments_count"] == 1 and len(b["recent_applications"]) == 2)
t("GET /applications landlord", ev("GET /applications", **L), 200, lambda b: len(b) == 2)
t("GET /applications student", ev("GET /applications", **S1), 403)

# messaging failure must not break the API
sns.fail = True
a3 = t("S1 applies room 2", ev("POST /applications", body={"room_id": 2, "move_in_date": "2026-12-01"}, **S1), 201)["application_id"]
t("approve with SNS down -> still 200", ev("PATCH /applications/{id}", pid=a3, body={"status": "approved"}, **L), 200, lambda b: b["notification_sent"] is False)
# earlier cases still hold
t("invalid room id", ev("GET /rooms/{id}", pid="abc"), 400)
t("unknown route", ev("GET /nope", **S1), 404)
print("\nFAILED: %d" % fails); sys.exit(1 if fails else 0)
