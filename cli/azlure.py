#!/usr/bin/env python3
# AzLure CLI — Automatic or Manual deployment wrapper for Terraform
import os
import sys
import json
import time
import click
import subprocess
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[1]
TF_DIR = ROOT / "infra" / "terraform"
EXAMPLES = ROOT / "examples" / "demo-config.yml"
STATE_DIR = ROOT / ".azlure"
STATE_DIR.mkdir(exist_ok=True)

BANNER = r"""
_                                  ______  ______
   / \     _____  |      |     |  |     /  |
  / _ \        /  |      |     |  |    /   |_____
 / ___ \     /    |      |     |  |   /    |
/_/   \_\  /____  |_____ |_____|  |   \    |_____

"""


def sh(cmd, cwd=None, env=None, capture=False):
    click.echo(click.style("> " + " ".join(cmd), fg="cyan"))
    if capture:
        return subprocess.check_output(cmd, cwd=cwd, env=env).decode("utf-8")
    subprocess.check_call(cmd, cwd=cwd, env=env)

def ensure_tools():
    for bin in ["terraform", "az", "python"]:
        if not shutil.which(bin):
            raise click.ClickException(f"{bin} not found on PATH.")

def load_cfg(path):
    with open(path, "r") as f:
        return yaml.safe_load(f)

def write_tfvars(cfg, outpath):
    """
    Writes or updates Terraform variables file.
    If file already exists, preserve the user's chosen 'location'
    and any other manually edited keys instead of overwriting.
    """
    import json

    # Load existing tfvars if present
    existing = {}
    if os.path.exists(outpath):
        try:
            with open(outpath, "r") as f:
                existing = json.load(f)
        except json.JSONDecodeError:
            existing = {}

    names = cfg["names"]

    # Merge user-edited values with defaults
    tfvars = existing.copy()
    tfvars.update({
        "tenant_domain": cfg.get("tenant_name", "secureorg.onmicrosoft.com"),
        # if location already set, keep it; otherwise use user config or fallback
        "location": existing.get("location", cfg.get("location", "southeastasia")),
        "resource_group": names.get("resource_group", "azlure-rg"),
        "public_storage_account_name": names.get("public_storage_account", "secureorgbackup"),
        "private_storage_account_name": names.get("private_storage_account", "secureorgpriv"),
        "public_container_name": names.get("public_container", "backup"),
        "private_container_name": names.get("private_container", "secrets"),
        "key_vault_name": names.get("key_vault", "kv-azlure"),
        "automation_account_name": names.get("automation_account", "Automatic Backup"),
        "randomize_names": True,
        "enable_log_analytics": cfg.get("logging", {}).get("enable_log_analytics", False),
        "create_key_vault": cfg["features"].get("create_key_vault", True),
        "create_automation_account": cfg["features"].get("create_automation_account", True),
        "create_app_registration": cfg["features"].get("create_app_registration", True),
        "grant_app_reader_on_rg": cfg["features"].get("grant_app_reader_on_rg", True),
        "grant_app_kv_secrets_user": cfg["features"].get("grant_app_kv_secrets_user", True),
        "grant_app_automation_contributor": cfg["features"].get("grant_app_automation_contributor", True),
    })

    with open(outpath, "w") as f:
        json.dump(tfvars, f, indent=2)

    return outpath


def print_step(msg, url=None):
    if url:
        click.echo(click.style(f"{msg} → {url}", fg="green"))
    else:
        click.echo(click.style(msg, fg="green"))

@click.group()
def cli():
    click.echo(click.style(BANNER, fg="magenta"))

@cli.command(help="Automatic mode: deploy with opinionated defaults")
@click.option("--config", "-c", default=str(EXAMPLES), help="YAML config (uses examples/demo-config.yml by default)")
@click.option("--yes", is_flag=True, help="Skip confirmation")
def auto(config, yes):
    cfg = load_cfg(config)
    cfg["mode"] = "auto"
    if not yes:
        click.confirm("Proceed with AzLure automatic deployment into your current Azure subscription?", abort=True)

    tfvars_path = STATE_DIR / "auto.tfvars.json"
    tfvars_path = write_tfvars(cfg, tfvars_path)

    # terraform init/plan/apply
    sh(["terraform", "init"], cwd=str(TF_DIR))
    sh(["terraform", "plan", "-var-file", str(tfvars_path), "-out", "tfplan"], cwd=str(TF_DIR))
    sh(["terraform", "apply", "tfplan"], cwd=str(TF_DIR))

    # fetch outputs
    out_json = sh(["terraform", "output", "-json"], cwd=str(TF_DIR), capture=True)
    outputs = json.loads(out_json)

    # User-facing progress
    list_url = outputs["public_container_list_url"]["value"]
    cred_url = outputs["public_credential_blob_url"]["value"]
    print_step("Configuring insecure storage blob, container available", list_url)
    print_step("Published foothold blob 'credential'", cred_url)

    if outputs.get("key_vault_uri", {}).get("value"):
        print_step("Key Vault deployed", outputs["key_vault_uri"]["value"])
    if outputs.get("automation_account_id", {}).get("value"):
        print_step("Automation Account deployed (RBAC granted to decoy SP)")

    click.echo(click.style("AzLure deployment complete.", fg="yellow"))

@cli.command(help="Manual mode: specify names yourself")
@click.option("--tenant", required=True, help="Tenant name e.g. contoso.onmicrosoft.com")
@click.option("--public-sa", required=True, help="Public storage account (must be globally unique)")
@click.option("--private-sa", required=True, help="Private storage account (must be globally unique)")
@click.option("--keyvault", required=True, help="Key Vault name")
@click.option("--automation", default="Automatic Backup", help="Automation Account name")
@click.option("--location", default="southeastasia")
@click.option("--yes", is_flag=True)
def manual(tenant, public_sa, private_sa, keyvault, automation, location, yes):
    cfg = load_cfg(EXAMPLES)
    cfg["mode"] = "manual"
    cfg["tenant_name"] = tenant
    cfg["location"] = location
    cfg["names"]["public_storage_account"] = public_sa
    cfg["names"]["private_storage_account"] = private_sa
    cfg["names"]["key_vault"] = keyvault
    cfg["names"]["automation_account"] = automation
    cfg["names"]["resource_group"] = "azlure-rg"

    if not yes:
        click.confirm(f"Deploy AzLure with your names (tenant={tenant})?", abort=True)

    tfvars_path = STATE_DIR / "manual.tfvars.json"
    tfvars_path = write_tfvars(cfg, tfvars_path)

    sh(["terraform", "init"], cwd=str(TF_DIR))
    sh(["terraform", "plan", "-var-file", str(tfvars_path), "-out", "tfplan"], cwd=str(TF_DIR))
    sh(["terraform", "apply", "tfplan"], cwd=str(TF_DIR))

    out_json = sh(["terraform", "output", "-json"], cwd=str(TF_DIR), capture=True)
    outputs = json.loads(out_json)
    list_url = outputs["public_container_list_url"]["value"]
    cred_url = outputs["public_credential_blob_url"]["value"]
    print_step("Configuring insecure storage blob, container available", list_url)
    print_step("Published foothold blob 'credential'", cred_url)
    click.echo(click.style("AzLure deployment complete.", fg="yellow"))

@cli.command(help="Destroy the honeypot (resource group)")
@click.option("--yes", is_flag=True)
def destroy(yes):
    if not yes:
        click.confirm("Destroy AzLure resources? This will remove the resource group.", abort=True)
    sh(["terraform", "destroy", "-auto-approve"], cwd=str(TF_DIR))
    click.echo(click.style("AzLure teardown complete.", fg="yellow"))
@cli.group(help="Manage or run the custom log analysis tool")
def logs():
    """Log analysis tool integration"""
    pass


@logs.command(help="Run the custom log analysis pipeline (stdout alerts)")
@click.option("--config", "-c", default="log_pipeline/config.yml", help="Path to log config YAML")
@click.option("--loop", is_flag=True, help="Run continuously in a loop")
@click.option("--interval", default=60, help="Polling interval in seconds (used with --loop)")
def run(config, loop, interval):
    """Run AzLure's custom log analysis"""
    import subprocess
    import sys
    import os
    from pathlib import Path

    root = Path(__file__).resolve().parents[1]
    parser_path = root / "log_pipeline" / "parser.py"

    if not parser_path.exists():
        click.echo(click.style("ERROR: log_pipeline/parser.py not found.", fg="red"))
        sys.exit(1)

    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(root))
    cmd = [sys.executable, str(parser_path), "--config", config]
    if loop:
        cmd += ["--loop", "--interval", str(interval)]
    else:
        cmd += ["--once"]

    click.echo(click.style("Starting AzLure log analysis tool...", fg="cyan"))
    try:
        subprocess.run(cmd, cwd=str(root), env=env)
    except KeyboardInterrupt:
        click.echo(click.style("\nLog analysis stopped by user.", fg="yellow"))


@logs.command(help="Run the custom log analysis pipeline (stdout alerts)")
@click.option("--config", "-c", default="log_pipeline/config.yml", help="Path to log config YAML")
@click.option("--loop", is_flag=True, help="Run continuously in a loop")
@click.option("--interval", default=60, help="Polling interval in seconds (used with --loop)")
def run(config, loop, interval):
    """Run AzLure's custom log analysis"""
    import subprocess
    import sys
    import os
    from pathlib import Path

    # Determine repo root dynamically — parent of cli/
    cli_dir = Path(__file__).resolve().parent
    repo_root = cli_dir.parent

    # Build absolute paths to the log pipeline files
    parser_path = repo_root / "log_pipeline" / "parser.py"
    config_path = repo_root / config

    if not parser_path.exists():
        click.echo(click.style(f"ERROR: parser.py not found at {parser_path}", fg="red"))
        click.echo(click.style("Hint: ensure log_pipeline/ is in the root of your 'azlure/' repo.", fg="yellow"))
        sys.exit(1)

    if not config_path.exists():
        click.echo(click.style(f"ERROR: Config not found at {config_path}", fg="red"))
        sys.exit(1)

    # Set environment and build command
    env = os.environ.copy()
    env.setdefault("PYTHONPATH", str(repo_root))
    cmd = [sys.executable, str(parser_path), "--config", str(config_path)]
    if loop:
        cmd += ["--loop", "--interval", str(interval)]
    else:
        cmd += ["--once"]

    click.echo(click.style("▶ Starting AzLure log analysis tool...", fg="cyan"))
    try:
        subprocess.run(cmd, cwd=str(repo_root), env=env)
    except KeyboardInterrupt:
        click.echo(click.style("\nLog analysis stopped by user.", fg="yellow"))




if __name__ == "__main__":
    import shutil
    try:
        cli()
    except subprocess.CalledProcessError as e:
        click.echo(click.style(f"Command failed: {e}", fg="red"))
        sys.exit(1)
