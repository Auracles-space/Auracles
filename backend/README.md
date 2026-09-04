# Auracles Backend

## Initial admin bootstrap

After applying migrations in a new local/staging/prod database, create the
first admin account with:

```bash
ADMIN_EMAIL=dev@auracles.space ADMIN_PASSWORD='replace-with-strong-password' uv run python -m scripts.bootstrap_admin
```

The command is idempotent. It creates the user and `admin` role if missing, and
does not store the plaintext password.

## TOTP encryption key

TOTP shared secrets are encrypted with `TOTP_ENCRYPTION_KEY`, separate from the
JWT `SECRET_KEY`. Generate a Fernet-format key with:

```bash
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Rotating this key without re-enrolling users makes existing TOTP secrets
unreadable.

## Environment files & local testing

`config.py` loads `.env` by default. Keep `.env` for **local/dev values only**
(copy from `.env.example`). Production secrets live in the Render
`auracles-secrets` env group — never commit them to `.env`.

To run a local process against remote/production values deliberately, put those
values in `.env.prod` (gitignored; template in `.env.prod.example`) and select
it with `ENV_FILE`:

```bash
ENV_FILE=.env.prod uv run uvicorn app.main:app
ENV_FILE=.env.prod uv run celery -A app.workers.celery_app worker
```

The test suite is always local and never reads `.env`/`.env.prod`:
`tests/conftest.py` pins localhost datastores and dev keys before settings load,
and a session guard (`tests/_guard.py`) hard-aborts `pytest` if a non-local
database or Redis host is ever resolved. Run tests with a plain `uv run pytest`.
