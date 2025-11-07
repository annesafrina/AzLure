terraform {
  required_version = ">= 1.5.0"

  required_providers {
    azurerm = {
      source  = "hashicorp/azurerm"
      version = "~> 3.114"
    }
    azuread = {
      source  = "hashicorp/azuread"
      version = "~> 2.50"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}

provider "azurerm" {
  features {}
}

provider "azuread" {}

data "azurerm_client_config" "current" {}

resource "random_string" "suffix" {
  length  = 4
  upper   = false
  numeric = true
  special = false
}

locals {
  rg_name   = var.resource_group
  pub_sa    = var.randomize_names ? "${var.public_storage_account_name}${random_string.suffix.result}" : var.public_storage_account_name
  prv_sa    = var.randomize_names ? "${var.private_storage_account_name}${random_string.suffix.result}" : var.private_storage_account_name
  pub_cont  = var.public_container_name
  prv_cont  = var.private_container_name
  kv_name   = var.key_vault_name
  auto_name = substr(
    replace(lower(coalesce(var.automation_account_name, "azlure-auto")), "/[^a-z0-9-]/", "-"),
    0,
    50
  )
}

# -----------------------------
# Resource Group
# -----------------------------
resource "azurerm_resource_group" "rg" {
  name     = local.rg_name
  location = var.location
  tags = {
    project = var.project_name
    purpose = "honeypot"
  }
}

# -----------------------------
# Storage Accounts (A=public, B=private)
# -----------------------------
resource "azurerm_storage_account" "public" {
  name                     = local.pub_sa
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  #allow_blob_public_access = true

  tags = {
    project = var.project_name
    role    = "public"
  }
}

resource "azurerm_storage_container" "public_backup" {
  name                  = local.pub_cont
  storage_account_name  = azurerm_storage_account.public.name
  container_access_type = "container" # listable container (comp=list)
}



resource "azurerm_storage_account" "private" {
  name                     = local.prv_sa
  resource_group_name      = azurerm_resource_group.rg.name
  location                 = azurerm_resource_group.rg.location
  account_tier             = "Standard"
  account_replication_type = "LRS"
  #allow_blob_public_access = false

  tags = {
    project = var.project_name
    role    = "private"
  }
}

resource "azurerm_storage_container" "private_secrets" {
  name                  = local.prv_cont
  storage_account_name  = azurerm_storage_account.private.name
  container_access_type = "private"
}

# -----------------------------
# App Registration (decoy SP) + secret
# realistic leak for external attackers
# -----------------------------
resource "azuread_application" "decoy" {
  count        = var.create_app_registration ? 1 : 0
  display_name = "${var.project_name}-decoy-sp"
}

resource "azuread_service_principal" "decoy" {
  count          = var.create_app_registration ? 1 : 0
  client_id      = azuread_application.decoy[0].client_id
  depends_on     = [azuread_application.decoy]
}

resource "azuread_application_password" "decoy_secret" {
  count                 = var.create_app_registration ? 1 : 0
  application_object_id = azuread_application.decoy[0].object_id
  display_name          = "azlure-demo"
  end_date_relative     = "720h" # ~30 days (short-lived)
}

# -----------------------------
# RBAC: grant SP Reader on RG (for enumeration realism)
# -----------------------------
resource "azurerm_role_assignment" "sp_reader_rg" {
  count                = var.create_app_registration && var.grant_app_reader_on_rg ? 1 : 0
  scope                = azurerm_resource_group.rg.id
  role_definition_name = "Reader"
  principal_id         = azuread_service_principal.decoy[0].object_id
}

# -----------------------------
# Key Vault (optional) + secret; and allow SP to read secrets (RBAC)
# -----------------------------
resource "azurerm_key_vault" "kv" {
  count                       = var.create_key_vault ? 1 : 0
  name                        = local.kv_name
  location                    = azurerm_resource_group.rg.location
  resource_group_name         = azurerm_resource_group.rg.name
  tenant_id                   = data.azurerm_client_config.current.tenant_id
  sku_name                    = "standard"
  purge_protection_enabled    = false
  soft_delete_retention_days  = 7
  enable_rbac_authorization   = true

  tags = {
    project = var.project_name
    role    = "decoy-kv"
  }
}

# KV Secret (decoy)
resource "azurerm_key_vault_secret" "kv_idrsa" {
  count        = var.create_key_vault ? 1 : 0
  name         = "id-rsa"
  key_vault_id = azurerm_key_vault.kv[0].id
  value        = "-----BEGIN OPENSSH PRIVATE KEY-----\nFAKE_PRIVATE_KEY_DO_NOT_USE\n-----END OPENSSH PRIVATE KEY-----"
  content_type = "text/plain"
  depends_on   = [azurerm_key_vault.kv]
}

# RBAC: SP can read secrets (Key Vault Secrets User)
data "azurerm_role_definition" "kv_secrets_user" {
  count = var.create_key_vault && var.create_app_registration && var.grant_app_kv_secrets_user ? 1 : 0
  name  = "Key Vault Secrets User"
  scope = azurerm_key_vault.kv[0].id
}

resource "azurerm_role_assignment" "sp_kv_reader" {
  count                = var.create_key_vault && var.create_app_registration && var.grant_app_kv_secrets_user ? 1 : 0
  scope                = azurerm_key_vault.kv[0].id
  role_definition_id   = data.azurerm_role_definition.kv_secrets_user[0].id
  principal_id         = azuread_service_principal.decoy[0].object_id
  depends_on           = [azurerm_key_vault.kv, azuread_service_principal.decoy]
}

# -----------------------------
# Automation Account (optional) and SP role
# -----------------------------
resource "azurerm_automation_account" "auto" {
  count               = var.create_automation_account ? 1 : 0
  name                = local.auto_name
  location            = azurerm_resource_group.rg.location
  resource_group_name = azurerm_resource_group.rg.name
  sku_name            = "Basic"

  tags = {
    project = var.project_name
    role    = "decoy-automation"
  }
}

data "azurerm_role_definition" "automation_contrib" {
  count = var.create_automation_account && var.create_app_registration && var.grant_app_automation_contributor ? 1 : 0
  name  = "Automation Contributor"
  scope = azurerm_automation_account.auto[0].id
}

resource "azurerm_role_assignment" "sp_automation_contrib" {
  count               = var.create_automation_account && var.create_app_registration && var.grant_app_automation_contributor ? 1 : 0
  scope               = azurerm_automation_account.auto[0].id
  role_definition_id  = data.azurerm_role_definition.automation_contrib[0].id
  principal_id        = azuread_service_principal.decoy[0].object_id
}

# -----------------------------
# Private blob with decoy SP creds (secret.txt)
# -----------------------------
resource "azurerm_storage_blob" "private_secret" {
  name                   = "secret.txt"
  storage_account_name   = azurerm_storage_account.private.name
  storage_container_name = azurerm_storage_container.private_secrets.name
  type                   = "Block"
  content_type           = "text/plain"

  source_content = <<EOT
# AzLure decoy credentials (demo)
client_id=${var.create_app_registration ? azuread_application.decoy[0].client_id : "FAKE_CLIENT_ID"}
client_secret=${var.create_app_registration ? azuread_application_password.decoy_secret[0].value : "FAKE_SECRET"}
tenant=${var.tenant_domain}
note=Decoy SP has Reader on RG and Key Vault Secrets User on KV (demo).
EOT
}

# -----------------------------
# Generate an account-level SAS (read-only, blob service, objects only)
# -----------------------------
data "azurerm_storage_account_sas" "private_read" {
  connection_string = azurerm_storage_account.private.primary_connection_string

  https_only = true
  start      = timeadd(timestamp(), "-5m")
  expiry     = timeadd(timestamp(), "168h") # 7 days

  resource_types {
    service   = false
    container = false
    object    = true
  }

  services {
    blob = true
    file = false
    queue = false
    table = false
  }

  permissions {
    read    = true
    write   = false
    delete  = false
    list    = false
    add     = false
    create  = false
    update  = false
    process = false
    tag     = false
    filter  = false
  }
}

# Public blob 'credential' pointing to the private secret via SAS
resource "azurerm_storage_blob" "public_credential" {
  name                   = "credential"
  storage_account_name   = azurerm_storage_account.public.name
  storage_container_name = azurerm_storage_container.public_backup.name
  type                   = "Block"
  content_type           = "text/plain"

  source_content = <<EOT
# Use this to fetch latest backup manifest
${format("https://%s.blob.core.windows.net/%s/%s%s",
  azurerm_storage_account.private.name,
  azurerm_storage_container.private_secrets.name,
  azurerm_storage_blob.private_secret.name,
  data.azurerm_storage_account_sas.private_read.sas
)}
EOT
}

# -----------------------------
# Optional: hook up diagnostics later (disabled by default)
# -----------------------------
# resource "azurerm_monitor_diagnostic_setting" "storage_public_diag" { ... }

# -----------------------------
# Outputs
# -----------------------------
output "public_container_list_url" {
  value = format("https://%s.blob.core.windows.net/%s?restype=container&comp=list", azurerm_storage_account.public.name, azurerm_storage_container.public_backup.name)
}

output "public_credential_blob_url" {
  value = format("https://%s.blob.core.windows.net/%s/%s",
    azurerm_storage_account.public.name,
    azurerm_storage_container.public_backup.name,
    azurerm_storage_blob.public_credential.name)
}

output "private_secret_blob_sas_url" {
  value = format("https://%s.blob.core.windows.net/%s/%s%s",
    azurerm_storage_account.private.name,
    azurerm_storage_container.private_secrets.name,
    azurerm_storage_blob.private_secret.name,
    data.azurerm_storage_account_sas.private_read.sas)
  sensitive = true
}

output "decoy_app_client_id" {
  value     = var.create_app_registration ? azuread_application.decoy[0].client_id : ""
  sensitive = false
}

output "key_vault_uri" {
  value = var.create_key_vault ? azurerm_key_vault.kv[0].vault_uri : ""
}

output "automation_account_id" {
  value = var.create_automation_account ? azurerm_automation_account.auto[0].id : ""
}
