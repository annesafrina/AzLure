#!/usr/bin/env python3
# seeder/seed_backup_paths.py
# Usage:
#   python seed_backup_paths.py --connstr "<storage_connstr>" --kv-name "backup-vault" --resource-group "honeypot-rg"

import argparse, datetime, os, json
from jinja2 import Environment, FileSystemLoader
from azure.storage.blob import BlobServiceClient
from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

HERE = os.path.dirname(__file__)
TEMPLATES = os.path.join(HERE, "templates")

def render_template(name, ctx):
    env = Environment(loader=FileSystemLoader(TEMPLATES))
    tpl = env.get_template(name)
    return tpl.render(**ctx)

def upload_blob(conn_str, container, blob_name, data):
    client = BlobServiceClient.from_connection_string(conn_str)
    container_client = client.get_container_client(container)
    try:
        container_client.create_container()
    except Exception:
        pass
    blob_client = container_client.get_blob_client(blob_name)
    blob_client.upload_blob(data.encode('utf-8'), overwrite=True)
    print(f"[+] Uploaded {blob_name} to {container}")

def put_kv_secret(kv_name, secret_name, secret_value):
    kv_url = f"https://{kv_name}.vault.azure.net"
    cred = DefaultAzureCredential()
    client = SecretClient(vault_url=kv_url, credential=cred)
    client.set_secret(secret_name, secret_value)
    print(f"[+] Put secret {secret_name} into {kv_name}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--connstr", required=True)
    parser.add_argument("--container", default="public-backup")
    parser.add_argument("--kv-name", default="backup-vault")
    parser.add_argument("--resource-group", default="honeypot-rg")
    args = parser.parse_args()

    ts = datetime.datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    ctx = {"timestamp": ts, "vault": args.kv_name}

    # 1) seed deploy_history that contains an "id_rsa" entry (fake)
    deploy_history = render_template("deploy_history.txt.j2", ctx)
    upload_blob(args.connstr, args.container, "deploy_history.txt", deploy_history)

    # 2) seed id_rsa blob
    id_rsa = render_template("id_rsa.template", ctx)
    upload_blob(args.connstr, args.container, "id_rsa", id_rsa)

    # 3) seed a foothold pointer that references the KeyVault (so attacker finds it)
    foothold = render_template("foothold.txt.j2", ctx)
    upload_blob(args.connstr, args.container, "foothold.txt", foothold)

    # 4) write Key Vault secret (requires the identity/credential where this script runs to have SetSecret privilege)
    # We use DefaultAzureCredential; run this locally after 'az login' or from a service principal.
    try:
        put_kv_secret(args.kv_name, "backupCredential", "FAKE_BACKUP_SECRET")
    except Exception as e:
        print("[!] Failed to write Key Vault secret. Ensure this principal has SetSecret permission or skip this step.")
        print(e)

    # 5) print a simulated SAS url (SAFE FAKE)
    fake_sas = f"https://{os.environ.get('SIMULATED_SAS_HOST','storageaccount')}.blob.core.windows.net/{args.container}/foothold.txt?sv=FAKE_SAS&sig=FAKE"
    print("[+] Simulated SAS (FAKE):", fake_sas)

if __name__ == "__main__":
    main()
