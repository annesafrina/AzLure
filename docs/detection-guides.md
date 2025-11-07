# Detection (when you later enable logging)

## Storage hits (public container & SAS usage)
- Watch for GETs to:
  - `/backup?restype=container&comp=list`
  - `/backup/credential`
  - SAS URLs containing `sv=`, `sig=`, `sp=`

## AAD / SP sign-ins
- Alert on ServicePrincipalSignInLogs where AppId == decoy SP client_id.

## Key Vault access
- Alert on `SecretGet` for secret name `id_rsa`.

## Automation Account access
- Unusual ARM reads on Automation Account resources under the honeypot RG.
