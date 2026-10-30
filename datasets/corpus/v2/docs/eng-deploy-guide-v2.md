# Production Deployment Guide (revision 2)

## Deployment windows

Production deployments are allowed Monday to Thursday between 10:00 and 16:00. On Friday, deployments are frozen after 12:00. No deployments are allowed on public holidays.

## Approvals

Every production deployment needs approval from two engineers, one of whom must be from the owning team.

## Rollback

If the error rate stays above 1% for 5 minutes after a deployment, the deploying engineer must roll back within 10 minutes.
