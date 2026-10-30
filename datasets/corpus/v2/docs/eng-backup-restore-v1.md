# Database Backup and Restore Runbook

## Backup schedule

Production databases are backed up nightly at 01:00. Backups are encrypted and stored in a separate account. Backups are retained for 14 days.

## Restore testing

A restore test is performed every quarter on a copy of the production database. The test result is recorded in the operations log.

## Restoring production

1. Declare an incident and inform the incident commander before any production restore.
2. Restore the most recent backup to a new database instance; never overwrite the running database.
3. Verify row counts on the main tables before switching the application to the restored instance.

## Ownership

The platform team owns backups. Changes to the backup schedule need approval from the engineering manager.
