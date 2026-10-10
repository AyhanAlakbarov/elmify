# Runbook: restore drill

`scripts/restore_backup.sh` proves the point-in-time recovery (PITR) path
works without touching the live `Database` (`BackupRetentionPeriod: 7`,
`StorageEncrypted: true`) or the live `EvidenceBucket` (versioned).

## Running a drill

```bash
export AWS_REGION=eu-central-1
export RESTORE_DB_PASSWORD=<Database master password from Secrets Manager>
bash scripts/restore_backup.sh tehsil-agent-production
```

Optionally pass a specific restore time as the second argument
(`YYYY-MM-DDTHH:MM:SSZ`); defaults to 5 minutes before the drill starts.

What it does, in order:

1. Looks up the live `Database`'s physical instance id from the stack.
2. `aws rds restore-db-instance-to-point-in-time` into a disposable
   `<stack-name>-restore-<timestamp>` instance (`--no-publicly-accessible`,
   tagged `Purpose=restore-drill`), and waits for it to become available.
3. Runs one read-only integrity query (`pg_tables` row count) against the
   restored instance.
4. Confirms `EvidenceBucket` returns object versions via
   `s3api list-object-versions` (proves S3 versioning is doing its job
   independently of the RDS restore).
5. On exit — success or failure — deletes only the disposable restore
   instance it created (`trap cleanup EXIT`, `--skip-final-snapshot`). It
   never issues a delete against the live `Database`.

## Cadence

Run this drill at least quarterly and after any change to
`BackupRetentionPeriod`, storage encryption, or the RDS engine version.
Record the run's timestamp and pass/fail in the deploy environment's
operational log.

## If the drill fails

Treat as a data-durability incident, not a deploy blocker — the live
database is untouched by a failed drill. Escalate before the next real
restore is needed; a failed drill means the actual recovery path is
unproven.
