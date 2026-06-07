# Auracles Backend

## Initial admin bootstrap

After applying migrations in a new local/staging/prod database, create the
first admin account with:

```bash
ADMIN_EMAIL=admin@auracles.space ADMIN_PASSWORD='replace-with-strong-password' uv run python -m scripts.bootstrap_admin
```

The command is idempotent. It creates the user and `admin` role if missing, and
does not store the plaintext password.
