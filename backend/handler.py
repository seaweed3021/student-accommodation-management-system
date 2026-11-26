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

LANDLORD = "landlord"
STATUS = "status"
APP_ID = "application_id"
ROOM_ID = "room_id"
MOVE_IN = "move_in_date"
APPROVED = "approved"
REJECTED = "rejected"
AVAILABLE = "available"
INVALID_APP_ID = "invalid application id"
APP_NOT_FOUND = "application not found"
ROOM_TAKEN = "room is no longer available"
CUSTOMERS_ONLY = "customers only"
LANDLORD_ONLY = "landlord only"
# one source for the join that several queries share
APP_JOIN = "FROM applications a JOIN rooms r USING(room_id) "


def _db():
    global _conn
    if _conn is None:
        _conn = pg8000.native.Connection(
            host=os.environ["DB_HOST"],
            port=int(os.environ.get("DB_PORT", "5432")),
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


def _error(status, message):
    return _resp(status, {"error": message})


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
    keys = [ROOM_ID, "title", "description", "monthly_rent", "status",
            "available_from", "property", "city"]
    return [dict(zip(keys, row)) for row in rows]


def _room(room_id):
    return next((r for r in _rooms() if r[ROOM_ID] == room_id), None)


def _apply(event, claims):
    try:
        data = json.loads(event.get("body") or "{}")
        room_id = int(data[ROOM_ID])
        move_in = str(data[MOVE_IN])
    except (ValueError, KeyError, TypeError):
        return _error(400, "room_id and move_in_date are required")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", move_in):
        return _error(400, "move_in_date must be YYYY-MM-DD")
    if not _room(room_id):
        return _error(404, "room not found")

    sub = claims.get("sub")
    # first sign-in: create the users row from the token (Cognito sub links the login)
    _run(
        "INSERT INTO users(cognito_sub, full_name, email, role) "
        "VALUES (:s, :n, :e, 'student') ON CONFLICT (cognito_sub) DO NOTHING",
        s=sub,
        n=claims.get("name") or claims.get("email", "Student"),
        e=claims.get("email", sub + "@unknown.invalid"),
    )
    student_id = _my_user_id(sub)
    row = _run(
        "INSERT INTO applications(room_id, student_id, move_in_date, message) "
        "VALUES (:r, :st, :d, :m) RETURNING application_id, status",
        r=room_id, st=student_id, d=move_in, m=data.get("message"),
    )[0]
    return _resp(201, {APP_ID: row[0], STATUS: row[1]})


def _applications():
    rows = _run(
        "SELECT a.application_id, r.title, u.full_name, a.status, a.move_in_date, a.submitted_at "
        + APP_JOIN +
        "JOIN users u ON u.user_id = a.student_id ORDER BY a.application_id"
    )
    keys = [APP_ID, "room", "student", STATUS, MOVE_IN, "submitted_at"]
    return [dict(zip(keys, r)) for r in rows]


def _list_applications(_event, _c):
    return _resp(200, _applications())


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
        except Exception as rollback_exc:
            print("ROLLBACK_FAILED", repr(rollback_exc))
        raise


def _app_id(event):
    try:
        return int(event["pathParameters"]["id"])
    except (ValueError, KeyError, TypeError):
        return None


def _my_user_id(sub):
    rows = _run("SELECT user_id FROM users WHERE cognito_sub = :s", s=sub)
    return rows[0][0] if rows else None


def _my_applications(_event, claims):
    uid = _my_user_id(claims["sub"])
    if uid is None:
        return _resp(200, [])
    rows = _run(
        "SELECT a.application_id, r.title, r.monthly_rent, a.status, a.move_in_date, "
        "a.submitted_at, a.decided_at, p.status, p.reference "
        + APP_JOIN +
        "LEFT JOIN payments p ON p.application_id = a.application_id "
        "WHERE a.student_id = :u ORDER BY a.application_id DESC", u=uid)
    keys = [APP_ID, "room", "monthly_rent", STATUS, MOVE_IN,
            "submitted_at", "decided_at", "payment_status", "payment_reference"]
    return _resp(200, [dict(zip(keys, r)) for r in rows])   # landlord_note is never selected


def _parse_decision(event):
    """Return (new_status, note, error_response). error_response is None when valid."""
    try:
        data = json.loads(event.get("body") or "{}")
        new_status = data[STATUS]
    except (ValueError, KeyError, TypeError):
        return None, None, _error(400, "status is required")
    if new_status not in (APPROVED, REJECTED):
        return None, None, _error(400, "status must be approved or rejected")
    note = data.get("landlord_note")
    if note is not None and len(str(note)) > 1000:
        return None, None, _error(400, "landlord_note too long")
    return new_status, note, None


def _decide(event, _c):
    app_id = _app_id(event)
    if app_id is None:
        return _error(400, INVALID_APP_ID)
    new_status, note, error = _parse_decision(event)
    if error:
        return error

    cur = _run("SELECT a.status, r.status, r.title " + APP_JOIN +
               "WHERE a.application_id = :i", i=app_id)
    if not cur:
        return _error(404, APP_NOT_FOUND)
    current_status, room_status, title = cur[0]
    if new_status == APPROVED and room_status != AVAILABLE:
        return _error(409, ROOM_TAKEN)
    # conditional update: only an undecided application can be decided (no double decisions)
    row = _run(
        "UPDATE applications SET status = :s, landlord_note = :n, decided_at = now() "
        "WHERE application_id = :i AND status IN ('submitted', 'under_review') "
        "RETURNING application_id, status", s=new_status, n=note, i=app_id)
    if not row:
        return _error(409, "application already " + current_status)
    sent = _notify(
        f"RoomSphere: application {app_id} {new_status}",
        f"Application {app_id} for {title} was {new_status}.")
    return _resp(200, {APP_ID: row[0][0], STATUS: row[0][1], "notification_sent": sent})


def _record_payment(app_id, uid, app, ref):
    """Inside one transaction: payment row, tenancy, room occupied. Returns 'ok', 'paid' or 'room'."""
    room_id, move_in, rent = app[ROOM_ID], app["move_in"], app["rent"]

    def work():
        if _run("SELECT 1 FROM payments WHERE application_id = :i", i=app_id):
            return "paid"
        locked = _run("UPDATE rooms SET status = 'occupied' "
                      "WHERE room_id = :r AND status = 'available' RETURNING room_id", r=room_id)
        if not locked:
            return "room"
        _run("INSERT INTO payments(application_id, amount, reference) VALUES (:i, :a, :ref)",
             i=app_id, a=rent, ref=ref)
        _run("INSERT INTO tenancies(application_id, room_id, student_id, start_date) "
             "VALUES (:i, :r, :u, :d)", i=app_id, r=room_id, u=uid, d=move_in)
        return "ok"

    return _tx(work)


def _pay(event, claims):
    """Mock deposit payment (stands in for Stripe sandbox; no card data is stored)."""
    app_id = _app_id(event)
    if app_id is None:
        return _error(400, INVALID_APP_ID)
    try:
        data = json.loads(event.get("body") or "{}")
    except ValueError:
        return _error(400, "invalid JSON")
    last4 = str(data.get("card_last4", "4242"))
    if not re.fullmatch(r"\d{4}", last4):
        return _error(400, "card_last4 must be 4 digits")

    uid = _my_user_id(claims["sub"])
    rows = _run(
        "SELECT a.status, a.room_id, a.move_in_date, r.monthly_rent, r.title "
        + APP_JOIN + "WHERE a.application_id = :i AND a.student_id = :u", i=app_id, u=uid)
    if not rows:   # not found OR not yours: same answer, no information leak
        return _error(404, APP_NOT_FOUND)
    status, room_id, move_in, rent, title = rows[0]
    if status != APPROVED:
        return _error(409, "application must be approved before payment")
    if last4 == "0002":   # test card that always declines, to demo error handling
        return _error(402, "card declined")

    ref = "MOCK-" + uuid.uuid4().hex[:12].upper()
    result = _record_payment(app_id, uid, {ROOM_ID: room_id, "move_in": move_in, "rent": rent}, ref)
    if result == "paid":
        return _error(409, "already paid")
    if result == "room":
        return _error(409, ROOM_TAKEN)
    sent = _notify(f"RoomSphere: payment received ({ref})",
                   f"Deposit of {float(rent):.2f} received for {title}. Reference {ref}.")
    return _resp(201, {"payment_reference": ref, "amount": rent, STATUS: "paid",
                       "notification_sent": sent})


def _show_dashboard(_event, _c):
    return _resp(200, _dashboard())


def _dashboard():
    rooms = {r[0]: r[1] for r in _run("SELECT status, count(*) FROM rooms GROUP BY status")}
    apps = {r[0]: r[1] for r in _run("SELECT status, count(*) FROM applications GROUP BY status")}
    total_rooms = sum(rooms.values())
    occupied = rooms.get("occupied", 0)
    money = _run("SELECT COALESCE(SUM(amount), 0), count(*) FROM payments WHERE status = 'paid'")[0]
    potential = _run("SELECT COALESCE(SUM(monthly_rent), 0) FROM rooms WHERE status = 'occupied'")[0][0]
    recent = _applications()[-5:][::-1]
    return {
        "rooms": {"total": total_rooms, "available": rooms.get(AVAILABLE, 0),
                  "occupied": occupied, "unavailable": rooms.get("unavailable", 0)},
        "occupancy_rate": round(100.0 * occupied / total_rooms, 1) if total_rooms else 0.0,
        "applications": {"total": sum(apps.values()),
                         "pending": apps.get("submitted", 0) + apps.get("under_review", 0),
                         APPROVED: apps.get(APPROVED, 0), REJECTED: apps.get(REJECTED, 0)},
        "monthly_rent_roll": potential,
        "deposits_collected": money[0],
        "payments_count": money[1],
        "recent_applications": recent,
    }


def _health(_event, _c):
    _run("SELECT 1")
    return _resp(200, {STATUS: "ok"})


def _list_rooms(_event, _c):
    return _resp(200, _rooms())


def _get_room(event, _c):
    try:
        room = _room(int(event["pathParameters"]["id"]))
    except (ValueError, KeyError, TypeError):
        return _error(400, "invalid room id")
    return _resp(200, room) if room else _error(404, "room not found")


# Route tables. API Gateway checks the Cognito token on the protected routes; the Lambda then
# applies the role rule: customers = any signed-in user outside the landlord group.
PUBLIC_ROUTES = {
    "GET /health": _health,
    "GET /rooms": _list_rooms,
    "GET /rooms/{id}": _get_room,
}
CUSTOMER_ROUTES = {
    "POST /applications": _apply,
    "GET /applications/mine": _my_applications,
    "POST /applications/{id}/payment": _pay,
}
LANDLORD_ROUTES = {
    "GET /applications": _list_applications,
    "PATCH /applications/{id}": _decide,
    "GET /dashboard": _show_dashboard,
}


def _dispatch(route, event):
    if route in PUBLIC_ROUTES:
        return PUBLIC_ROUTES[route](event, {})
    claims = _claims(event)
    if not claims.get("sub"):
        return _error(401, "sign in required")
    is_landlord = LANDLORD in _groups(claims)
    if route in CUSTOMER_ROUTES:
        if is_landlord:
            return _error(403, CUSTOMERS_ONLY)
        return CUSTOMER_ROUTES[route](event, claims)
    if route in LANDLORD_ROUTES:
        if not is_landlord:
            return _error(403, LANDLORD_ONLY)
        return LANDLORD_ROUTES[route](event, claims)
    return _error(404, "not found")


def handler(event, _context):
    route = event.get("routeKey") or ""
    try:
        return _dispatch(route, event)
    except Exception as exc:  # log the detail, never return it to the client
        print("ERROR", route, repr(exc))
        return _error(500, "internal error")


def init_handler(event, _context):
    """One-time: load schema.sql (and optional sample data) into RDS."""
    conn = pg8000.native.Connection(
        host=os.environ["DB_HOST"],
        port=int(os.environ.get("DB_PORT", "5432")),
        database=os.environ.get("DB_NAME", "roomsphere"),
        user=os.environ.get("DB_USER", "roomsphere_admin"),
        password=os.environ["DB_PASSWORD"],
        timeout=10,
    )

    # Read-only diagnostic mode: list existing tables.
    if event.get("check"):
        tables = [r[0] for r in conn.run(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' ORDER BY 1"
        )]
        conn.close()
        return {"existing_tables": tables}

    # Avoid reinitializing an existing database.
    exists = conn.run("SELECT to_regclass('public.users')")[0][0]
    if exists:
        conn.close()
        return {"loaded": False, "reason": "schema already present"}

    here = os.path.dirname(__file__)
    with open(os.path.join(here, "schema.sql"), encoding="utf-8") as f:
        conn.run(f.read())
    if event.get("seed"):
        with open(os.path.join(here, "seed.sql"), encoding="utf-8") as f:
            conn.run(f.read())

    tables = [r[0] for r in conn.run(
        "SELECT table_name FROM information_schema.tables "
        "WHERE table_schema='public' ORDER BY 1"
    )]
    conn.close()
    return {"loaded": True, "tables": tables}
