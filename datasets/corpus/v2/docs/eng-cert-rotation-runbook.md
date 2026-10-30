# TLS Certificate Rotation Runbook

## Symptoms

The certificate monitor raises a warning 21 days before a certificate expires and a critical alert 7 days before expiry. Expired certificates break customer API calls and the shipment tracking portal.

## Escalation

Rotation of a wildcard certificate or of any certificate used by the payment gateway requires approval from the security team before it is deployed.

## Steps

1. Certificates must be rotated at least 30 days before they expire. Request the new certificate through the certificate manager, never by emailing private keys.
2. Deploy the new certificate to the staging load balancer first and run the TLS check script.
3. Deploy to production during a normal deployment window and confirm that the certificate monitor shows the new expiry date.

## Rollback

If clients fail to connect after the change, restore the previous certificate from the certificate manager. The previous certificate stays available until it expires.
