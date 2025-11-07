# Deployment Notes

- Default (Automatic): tenant `secureorg.onmicrosoft.com`, public container `backup` is listable.
- `credential` blob holds a SAS URL pointing to a private blob `secret.txt` in a separate storage account.
- The private blob contains **App Registration creds** (client_id + client_secret).
- The App Registration has **Reader on the RG**, **Key Vault Secrets User** on the honeypot Key Vault, and **Automation Contributor** on the "Automatic Backup" Automation Account.

## Privileges required
- Azure subscription: **Contributor** (to create RG/resources).
- Azure AD: **Application Administrator** or equivalent to create App Registrations/Service Principals.

## Safety
- All creds are decoys.
- The SP secret is short‑lived (~30 days by default). You can reduce it further in Terraform.

## Teardown
Use `python cli/azlure.py destroy --yes`.
