"""Cloud persistence: users and saved projects.

Production points DATABASE_URL at a hosted Postgres (Neon). Locally and in
tests it falls back to SQLite, so the app still runs with zero setup. Only
SQLAlchemy Core is used -- the schema is two tables and needs no ORM.

Neon notes: connections are TLS-only (keep `sslmode=require` in the URL Neon
gives you) and idle computes are suspended, so the pool pre-pings and
recycles connections instead of handing out dead sockets.
"""
import datetime as dt
import os

from sqlalchemy import (JSON, Column, DateTime, ForeignKey, Integer, MetaData,
                        String, Table, Text, create_engine, func, insert, select,
                        update, delete)
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.pool import StaticPool
from werkzeug.security import check_password_hash, generate_password_hash

# Who the person is decides how detailed their report is:
#   homeowner  budget, water and the products (self-registration)
#   architect  + dimensions, clearances, placement schedule (self-registration)
#   kohler     + AI pipeline trace, selection maths, SKU detail (granted by an admin)
#   admin      the reviewing authority; sees the Kohler-level report
ROLES = ("homeowner", "architect", "kohler", "admin")
SELF_SERVICE_ROLES = ("homeowner", "architect")
LEGACY_ROLES = {"user": "homeowner"}      # accounts created before personas existed
PROJECT_STATUSES = ("draft", "submitted", "approved", "rejected")

metadata = MetaData()

users = Table(
    "users", metadata,
    Column("id", Integer, primary_key=True),
    Column("email", String(255), unique=True, nullable=False, index=True),
    Column("name", String(120), nullable=False, default=""),
    Column("password_hash", String(255), nullable=False),
    Column("role", String(16), nullable=False, default="homeowner"),
    Column("created_at", DateTime(timezone=True), nullable=False),
)

projects = Table(
    "projects", metadata,
    Column("id", Integer, primary_key=True),
    Column("owner_id", Integer, ForeignKey("users.id", ondelete="CASCADE"),
           nullable=False, index=True),
    Column("name", String(200), nullable=False),
    Column("data", JSON, nullable=False),
    Column("status", String(16), nullable=False, default="draft"),
    Column("review_note", Text, nullable=True),
    Column("reviewed_by", Integer, ForeignKey("users.id", ondelete="SET NULL"),
           nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False),
)

_engine = None


def _now():
    return dt.datetime.now(dt.timezone.utc)


def normalize_url(url):
    """Neon/Render hand out `postgres://` or `postgresql://` URLs; SQLAlchemy
    needs the driver named explicitly to use psycopg 3."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


def init_db(url=None):
    """Create the engine and tables. Safe to call more than once."""
    global _engine
    url = normalize_url(url or os.environ.get("DATABASE_URL") or "sqlite:///plumbline.db")
    if url.startswith("sqlite"):
        kwargs = {"connect_args": {"check_same_thread": False}}
        if url in ("sqlite://", "sqlite:///:memory:"):
            kwargs["poolclass"] = StaticPool       # one shared in-memory DB
        _engine = create_engine(url, **kwargs)
    else:
        _engine = create_engine(url, pool_pre_ping=True, pool_recycle=300,
                                pool_size=5, max_overflow=5)
    # Several gunicorn workers boot at once; on a fresh database they race to
    # create the schema and seed the admin. Losing that race is harmless, so
    # retry once instead of crashing the worker.
    try:
        metadata.create_all(_engine)
    except DBAPIError:
        metadata.create_all(_engine)
    _seed_admin()
    return _engine


def engine():
    if _engine is None:
        init_db()
    return _engine


def backend_name():
    return engine().dialect.name


def ping():
    try:
        with engine().connect() as c:
            c.execute(select(1))
        return True
    except Exception:                                   # noqa: BLE001
        return False


# -------------------------------------------------------------------- users --
def _public_user(row):
    if row is None:
        return None
    role = LEGACY_ROLES.get(row.role, row.role)
    return {"id": row.id, "email": row.email, "name": row.name, "role": role,
            "created_at": row.created_at.isoformat() if row.created_at else None}


def create_user(email, password, name="", role="homeowner"):
    """Returns the new user, or None if the email is taken."""
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    try:
        with engine().begin() as c:
            res = c.execute(insert(users).values(
                email=email.strip().lower(), name=name.strip(), role=role,
                password_hash=generate_password_hash(password), created_at=_now()))
            uid = res.inserted_primary_key[0]
    except IntegrityError:
        return None
    return get_user(uid)


def get_user(uid):
    with engine().connect() as c:
        return _public_user(c.execute(select(users).where(users.c.id == uid)).first())


def authenticate(email, password):
    with engine().connect() as c:
        row = c.execute(select(users).where(
            users.c.email == (email or "").strip().lower())).first()
    if row is None or not check_password_hash(row.password_hash, password or ""):
        return None
    return _public_user(row)


def list_users():
    with engine().connect() as c:
        counts = dict(c.execute(select(projects.c.owner_id, func.count())
                                .group_by(projects.c.owner_id)).all())
        rows = c.execute(select(users).order_by(users.c.id)).all()
    return [dict(_public_user(r), project_count=counts.get(r.id, 0)) for r in rows]


def set_role(uid, role):
    if role not in ROLES:
        raise ValueError(f"role must be one of {ROLES}")
    with engine().begin() as c:
        c.execute(update(users).where(users.c.id == uid).values(role=role))
    return get_user(uid)


def count_admins():
    with engine().connect() as c:
        return c.execute(select(func.count()).select_from(users)
                         .where(users.c.role == "admin")).scalar_one()


def _seed_admin():
    """Bootstrap the first authority account from the environment.

    ADMIN_EMAIL + ADMIN_PASSWORD create it (or promote an existing account).
    The password is only used on first creation; change it there afterwards.
    """
    email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    password = os.environ.get("ADMIN_PASSWORD", "")
    if not email or not password:
        return
    try:
        with engine().begin() as c:
            row = c.execute(select(users).where(users.c.email == email)).first()
            if row is None:
                c.execute(insert(users).values(
                    email=email, name="Administrator", role="admin", created_at=_now(),
                    password_hash=generate_password_hash(password)))
            elif row.role != "admin":
                c.execute(update(users).where(users.c.id == row.id).values(role="admin"))
    except IntegrityError:
        pass        # another worker seeded the same admin a moment earlier


# ----------------------------------------------------------------- projects --
def _project(row, owner_email=None, with_data=True):
    out = {"id": row.id, "owner_id": row.owner_id, "name": row.name,
           "status": row.status, "review_note": row.review_note,
           "created_at": row.created_at.isoformat(),
           "updated_at": row.updated_at.isoformat()}
    if owner_email is not None:
        out["owner_email"] = owner_email
    if with_data:
        out["data"] = row.data
    else:
        d = row.data or {}
        out["summary"] = d.get("summary") or {}
    return out


def create_project(owner_id, name, data):
    now = _now()
    with engine().begin() as c:
        res = c.execute(insert(projects).values(
            owner_id=owner_id, name=name, data=data, status="draft",
            created_at=now, updated_at=now))
        pid = res.inserted_primary_key[0]
    return get_project(pid)


def get_project(pid):
    with engine().connect() as c:
        row = c.execute(select(projects).where(projects.c.id == pid)).first()
    return _project(row) if row else None


def list_projects(owner_id=None, status=None):
    q = (select(projects, users.c.email.label("owner_email"))
         .join(users, users.c.id == projects.c.owner_id)
         .order_by(projects.c.updated_at.desc()))
    if owner_id is not None:
        q = q.where(projects.c.owner_id == owner_id)
    if status:
        q = q.where(projects.c.status == status)
    with engine().connect() as c:
        rows = c.execute(q).all()
    return [_project(r, owner_email=r.owner_email, with_data=False) for r in rows]


def update_project(pid, name=None, data=None):
    values = {"updated_at": _now()}
    if name is not None:
        values["name"] = name
    if data is not None:
        values["data"] = data
        # An edited design must be re-reviewed by an authority.
        values["status"] = "draft"
        values["review_note"] = None
    with engine().begin() as c:
        c.execute(update(projects).where(projects.c.id == pid).values(**values))
    return get_project(pid)


def set_project_status(pid, status, note=None, reviewer_id=None):
    if status not in PROJECT_STATUSES:
        raise ValueError(f"status must be one of {PROJECT_STATUSES}")
    values = {"status": status, "updated_at": _now()}
    if reviewer_id is not None:
        values.update(review_note=note, reviewed_by=reviewer_id)
    with engine().begin() as c:
        c.execute(update(projects).where(projects.c.id == pid).values(**values))
    return get_project(pid)


def delete_project(pid):
    with engine().begin() as c:
        return c.execute(delete(projects).where(projects.c.id == pid)).rowcount > 0


def stats():
    with engine().connect() as c:
        by_status = dict(c.execute(select(projects.c.status, func.count())
                                   .group_by(projects.c.status)).all())
        n_users = c.execute(select(func.count()).select_from(users)).scalar_one()
    return {"users": n_users, "projects": sum(by_status.values()),
            "by_status": {s: by_status.get(s, 0) for s in PROJECT_STATUSES}}
