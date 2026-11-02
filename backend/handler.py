"""RoomSphere API (AWS Lambda behind an API Gateway HTTP API).

Routes
  GET  /health            public
  GET  /rooms             public, lists rooms
  GET  /rooms/{id}        public
  POST /applications      any signed-in customer (not in the landlord group)
  GET  /applications      landlord group only: list all applications

API Gateway validates the Cognito JWT before this code runs. The handler
then checks the cognito:groups claim, so the owner role has elevated access.
"""
import json
import os
from decimal import Decimal
import re

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
        if route == "GET /applications":
            if "landlord" not in groups:
                return _resp(403, {"error": "landlord only"})
            return _resp(200, _applications())
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
