# Database Backup and Restore Runbook (revision 2)

## Backup schedule

Production databases are backed up every 6 hours, at 00:00, 06:00, 12:00 and 18:00. Point-in-time recovery is enabled for the last 7 days. Backups are encrypted and stored in a separate account. Backups are retained for 35 days.

## Restore testing

A restore test is performed every month on a copy of the production database. The test result, including the time the restore took, is recorded in the operations log.

## Restoring production

1. Declare an incident and inform the incident commander before any production restore.
2. Restore to a new database instance; never overwrite the running database.
3. Verify row counts on the main tables before switching the application to the restored instance.

## Ownership

The platform team owns backups. Changes to the backup schedule need approval from the engineering manager.
