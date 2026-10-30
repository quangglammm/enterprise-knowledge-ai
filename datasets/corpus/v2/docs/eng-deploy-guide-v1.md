# Production Deployment Guide

## Deployment windows

Production deployments are allowed Monday to Thursday between 10:00 and 16:00. On Friday, deployments are frozen after 15:00. No deployments are allowed on public holidays.

## Approvals

Every production deployment needs approval from two engineers, one of whom must be from the owning team.

## Rollback

If the error rate stays above 2% for 5 minutes after a deployment, the deploying engineer must roll back within 10 minutes.
