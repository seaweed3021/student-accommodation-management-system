"""RoomSphere API (AWS Lambda behind an API Gateway HTTP API).

Routes
  GET  /health            public
  GET  /rooms             public, lists rooms
  GET  /rooms/{id}        public
  POST /applications               any signed-in customer (not in the landlord group)
  GET  /applications/mine          the signed-in customer's own applications
  POST /applications/{id}/payment  the owning customer pays the deposit (mock provider)
  GET  /applications               landlord group only: list all applications
  PATCH /applications/{id}         landlord group only: approve or reject
  GET  /dashboard                  landlord group only: live numbers for the owner dashboard

API Gateway validates the Cognito JWT before this code runs. The handler
then checks the cognito:groups claim, so the owner role has elevated access.
"""
import json
import os
import re
import uuid
from decimal import Decimal

import pg8000.native

_conn = None


def _db():
    global _conn
    if _conn is None:
        _conn = pg8000.native.Connection(
            host=os.environ["DB_HOST"],
            database=os.environ.get("DB_NAME", "roomsphere"),
            user=os.environ.get("DB_USER", "roomsphere_admin"),
            password=os.environ["DB_PASSWORD"],
            timeout=5,
        )
    return _conn


def _run(sql, **params):
    """Run a query; reconnect once if the cached connection went stale."""
    global _conn
    try:
        return _db().run(sql, **params)
    except (pg8000.exceptions.InterfaceError, OSError):
        _conn = None
        return _db().run(sql, **params)


def _json_default(o):
    if isinstance(o, Decimal):
        return float(o)
    return str(o)


def _resp(status, body):
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_json_default),
    }


def _claims(event):
    return (
        event.get("requestContext", {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    )


def _groups(claims):
    raw = claims.get("cognito:groups", "")
    if isinstance(raw, list):
        return raw
    return [g for g in re.split(r"[\s,\[\]]+", str(raw)) if g]


def _rooms():
    rows = _run(
        "SELECT r.room_id, r.title, r.description, r.monthly_rent, r.status, "
        "r.available_from, p.name, p.city "
        "FROM rooms r JOIN properties p USING(property_id) ORDER BY r.room_id"
    )
    keys = ["room_id", "title", "description", "monthly_rent", "status",
            "available_from", "property", "city"]
    return [dict(zip(keys, row)) for row in rows]


def _room(room_id):
    return next((r for r in _rooms() if r["room_id"] == room_id), None)


def _apply(event, claims):
    try:
        data = json.loads(event.get("body") or "{}")
        room_id = int(data["room_id"])
        move_in = str(data["move_in_date"])
    except (ValueError, KeyError, TypeError):
        return _resp(400, {"error": "room_id and move_in_date are required"})
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", move_in):
        return _resp(400, {"error": "move_in_date must be YYYY-MM-DD"})
    if not _room(room_id):
        return _resp(404, {"error": "room not found"})

    sub = claims.get("sub")
    # first sign-in: create the users row from the token (Cognito sub links the login)
    _run(
        "INSERT INTO users(cognito_sub, full_name, email, role) "
        "VALUES (:s, :n, :e, 'student') ON CONFLICT (cognito_sub) DO NOTHING",
        s=sub,
        n=claims.get("name") or claims.get("email", "Student"),
        e=claims.get("email", sub + "@unknown.invalid"),
    )
    student_id = _run("SELECT user_id FROM users WHERE cognito_sub = :s", s=sub)[0][0]
    row = _run(
        "INSERT INTO applications(room_id, student_id, move_in_date, message) "
        "VALUES (:r, :st, :d, :m) RETURNING application_id, status",
        r=room_id, st=student_id, d=move_in, m=data.get("message"),
    )[0]
    return _resp(201, {"application_id": row[0], "status": row[1]})


def _applications():
    rows = _run(
        "SELECT a.application_id, r.title, u.full_name, a.status, a.move_in_date, a.submitted_at "
        "FROM applications a JOIN rooms r USING(room_id) "
        "JOIN users u ON u.user_id = a.student_id ORDER BY a.application_id"
    )
    keys = ["application_id", "room", "student", "status", "move_in_date", "submitted_at"]
    return [dict(zip(keys, r)) for r in rows]


_sns_client = None


def _notify(subject, message):
    """Best-effort SNS publish. A messaging failure never fails the API call.

    Returns True if SNS accepted the message. Runs over the SNS VPC endpoint
    because the private subnets have no NAT.
    """
    global _sns_client
    topic = os.environ.get("TOPIC_ARN")
    if not topic:
        return False
    try:
        if _sns_client is None:
            import boto3
            from botocore.config import Config
            _sns_client = boto3.client(
                "sns",
                region_name=os.environ.get("AWS_REGION", "us-east-1"),
                config=Config(connect_timeout=2, read_timeout=3, retries={"max_attempts": 1}),
            )
        _sns_client.publish(TopicArn=topic, Subject=subject[:100], Message=message)
        return True
    except Exception as exc:
        print("NOTIFY_FAILED", repr(exc))
        return False


def _tx(fn):
    """Run fn() inside one database transaction (all-or-nothing)."""
    _run("START TRANSACTION")
    try:
        out = fn()
        _run("COMMIT")
        return out
    except Exception:
        try:
            _run("ROLLBACK")
        except Exception:
            pass
        raise


def _app_id(event):
    try:
        return int(event["pathParameters"]["id"])
    except (ValueError, KeyError, TypeError):
        return None


def _my_user_id(sub):
    rows = _run("SELECT user_id FROM users WHERE cognito_sub = :s", s=sub)
    return rows[0][0] if rows else None


def _my_applications(claims):
    uid = _my_user_id(claims["sub"])
    if uid is None:
        return []
    rows = _run(
        "SELECT a.application_id, r.title, r.monthly_rent, a.status, a.move_in_date, "
        "a.submitted_at, a.decided_at, p.status, p.reference "
        "FROM applications a JOIN rooms r USING(room_id) "
        "LEFT JOIN payments p ON p.application_id = a.application_id "
        "WHERE a.student_id = :u ORDER BY a.application_id DESC", u=uid)
    keys = ["application_id", "room", "monthly_rent", "status", "move_in_date",
            "submitted_at", "decided_at", "payment_status", "payment_reference"]
    return [dict(zip(keys, r)) for r in rows]   # landlord_note is never selected


def _decide(event, claims):
    app_id = _app_id(event)
    if app_id is None:
        return _resp(400, {"error": "invalid application id"})
    try:
        data = json.loads(event.get("body") or "{}")
        new_status = data["status"]
    except (ValueError, KeyError, TypeError):
        return _resp(400, {"error": "status is required"})
    if new_status not in ("approved", "rejected"):
        return _resp(400, {"error": "status must be approved or rejected"})
    note = data.get("landlord_note")
    if note is not None and len(str(note)) > 1000:
        return _resp(400, {"error": "landlord_note too long"})

    cur = _run("SELECT a.status, r.status, r.title FROM applications a "
               "JOIN rooms r USING(room_id) WHERE a.application_id = :i", i=app_id)
    if not cur:
        return _resp(404, {"error": "application not found"})
    if new_status == "approved" and cur[0][1] != "available":
        return _resp(409, {"error": "room is no longer available"})
    # conditional update: only an undecided application can be decided (no double decisions)
    row = _run(
        "UPDATE applications SET status = :s, landlord_note = :n, decided_at = now() "
        "WHERE application_id = :i AND status IN ('submitted', 'under_review') "
        "RETURNING application_id, status", s=new_status, n=note, i=app_id)
    if not row:
        return _resp(409, {"error": "application already " + cur[0][0]})
    sent = _notify(
        "RoomSphere: application %d %s" % (app_id, new_status),
        "Application %d for %s was %s." % (app_id, cur[0][2], new_status))
    return _resp(200, {"application_id": row[0][0], "status": row[0][1], "notification_sent": sent})


def _pay(event, claims):
    """Mock deposit payment (stands in for Stripe sandbox; no card data is stored)."""
    app_id = _app_id(event)
    if app_id is None:
        return _resp(400, {"error": "invalid application id"})
    try:
        data = json.loads(event.get("body") or "{}")
    except ValueError:
        return _resp(400, {"error": "invalid JSON"})
    last4 = str(data.get("card_last4", "4242"))
    if not re.fullmatch(r"\d{4}", last4):
        return _resp(400, {"error": "card_last4 must be 4 digits"})

    uid = _my_user_id(claims["sub"])
    rows = _run(
        "SELECT a.status, a.room_id, a.move_in_date, r.monthly_rent, r.title "
        "FROM applications a JOIN rooms r USING(room_id) "
        "WHERE a.application_id = :i AND a.student_id = :u", i=app_id, u=uid)
    if not rows:   # not found OR not yours: same answer, no information leak
        return _resp(404, {"error": "application not found"})
    status, room_id, move_in, rent, title = rows[0]
    if status != "approved":
        return _resp(409, {"error": "application must be approved before payment"})
    if last4 == "0002":   # test card that always declines, to demo error handling
        return _resp(402, {"error": "card declined"})
    ref = "MOCK-" + uuid.uuid4().hex[:12].upper()

    def work():
        if _run("SELECT 1 FROM payments WHERE application_id = :i", i=app_id):
            return None
        locked = _run("UPDATE rooms SET status = 'occupied' "
                      "WHERE room_id = :r AND status = 'available' RETURNING room_id", r=room_id)
        if not locked:
            return "room"
        _run("INSERT INTO payments(application_id, amount, reference) VALUES (:i, :a, :ref)",
             i=app_id, a=rent, ref=ref)
        _run("INSERT INTO tenancies(application_id, room_id, student_id, start_date) "
             "VALUES (:i, :r, :u, :d)", i=app_id, r=room_id, u=uid, d=move_in)
        return "ok"

    result = _tx(work)
    if result is None:
        return _resp(409, {"error": "already paid"})
    if result == "room":
        return _resp(409, {"error": "room is no longer available"})
    sent = _notify("RoomSphere: payment received (%s)" % ref,
                   "Deposit of %.2f received for %s. Reference %s." % (float(rent), title, ref))
    return _resp(201, {"payment_reference": ref, "amount": rent, "status": "paid",
                       "notification_sent": sent})


def _dashboard():
    rooms = {r[0]: r[1] for r in _run("SELECT status, count(*) FROM rooms GROUP BY status")}
    apps = {r[0]: r[1] for r in _run("SELECT status, count(*) FROM applications GROUP BY status")}
    total_rooms = sum(rooms.values())
    occupied = rooms.get("occupied", 0)
    money = _run("SELECT COALESCE(SUM(amount), 0), count(*) FROM payments WHERE status = 'paid'")[0]
    potential = _run("SELECT COALESCE(SUM(monthly_rent), 0) FROM rooms WHERE status = 'occupied'")[0][0]
    recent = _applications()[-5:][::-1]
    return {
        "rooms": {"total": total_rooms, "available": rooms.get("available", 0),
                  "occupied": occupied, "unavailable": rooms.get("unavailable", 0)},
        "occupancy_rate": round(100.0 * occupied / total_rooms, 1) if total_rooms else 0.0,
        "applications": {"total": sum(apps.values()),
                         "pending": apps.get("submitted", 0) + apps.get("under_review", 0),
                         "approved": apps.get("approved", 0), "rejected": apps.get("rejected", 0)},
        "monthly_rent_roll": potential,
        "deposits_collected": money[0],
        "payments_count": money[1],
        "recent_applications": recent,
    }


def handler(event, context):
    route = event.get("routeKey") or ""
    try:
        if route == "GET /health":
            _run("SELECT 1")
            return _resp(200, {"status": "ok"})
        if route == "GET /rooms":
            return _resp(200, _rooms())
        if route == "GET /rooms/{id}":
            try:
                room = _room(int(event["pathParameters"]["id"]))
            except (ValueError, KeyError, TypeError):
                return _resp(400, {"error": "invalid room id"})
            return _resp(200, room) if room else _resp(404, {"error": "room not found"})

        claims = _claims(event)
        groups = _groups(claims)
        if not claims.get("sub"):
            return _resp(401, {"error": "sign in required"})
        if route == "POST /applications":
            # Self-signed-up users have no Cognito group; only the landlord group is special.
            if "landlord" in groups:
                return _resp(403, {"error": "customers only"})
            return _apply(event, claims)
        if route in ("GET /applications/mine", "POST /applications/{id}/payment"):
            if "landlord" in groups:
                return _resp(403, {"error": "customers only"})
            if route == "GET /applications/mine":
                return _resp(200, _my_applications(claims))
            return _pay(event, claims)
        if route in ("GET /applications", "PATCH /applications/{id}", "GET /dashboard"):
            if "landlord" not in groups:
                return _resp(403, {"error": "landlord only"})
            if route == "GET /applications":
                return _resp(200, _applications())
            if route == "GET /dashboard":
                return _resp(200, _dashboard())
            return _decide(event, claims)
        return _resp(404, {"error": "not found"})
    except Exception as exc:  # log the detail, never return it to the client
        print("ERROR", route, repr(exc))
        return _resp(500, {"error": "internal error"})


def init_handler(event, context):
    """One-time: load schema.sql (and optional sample data) into RDS."""
    conn = pg8000.native.Connection(
        host=os.environ["DB_HOST"],
        database=os.environ.get("DB_NAME", "roomsphere"),
        user=os.environ.get("DB_USER", "roomsphere_admin"),
        password=os.environ["DB_PASSWORD"],
        timeout=10,
    )
    exists = conn.run("SELECT to_regclass('public.users')")[0][0]
    if exists:
        conn.close()
        return {"loaded": False, "reason": "schema already present"}
    here = os.path.dirname(__file__)
    with open(os.path.join(here, "schema.sql")) as f:
        conn.run(f.read())  # simple query protocol runs the whole script
    if event.get("seed"):
        with open(os.path.join(here, "seed.sql")) as f:
            conn.run(f.read())
    tables = [r[0] for r in conn.run(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY 1")]
    conn.close()
    return {"loaded": True, "tables": tables}
