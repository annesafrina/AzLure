variable "enable_storage_diagnostics_to_storage" {
  type    = bool
  default = false
}

# Route public storage logs to the PRIVATE storage account (cheap central sink)
resource "azurerm_monitor_diagnostic_setting" "public_to_priv_logs" {
  count               = var.enable_storage_diagnostics_to_storage ? 1 : 0
  name                = "pub-to-priv-logs"
  target_resource_id  = azurerm_storage_account.public.id
  storage_account_id  = azurerm_storage_account.private.id

  log {
    category = "StorageRead"
    enabled  = true
  }

  metric {
    category = "AllMetrics"
    enabled  = false
  }
}

# Route private storage logs to itself (or keep in same private SA)
resource "azurerm_monitor_diagnostic_setting" "private_to_priv_logs" {
  count               = var.enable_storage_diagnostics_to_storage ? 1 : 0
  name                = "priv-to-priv-logs"
  target_resource_id  = azurerm_storage_account.private.id
  storage_account_id  = azurerm_storage_account.private.id

  log {
    category = "StorageRead"
    enabled  = true
  }

  metric {
    category = "AllMetrics"
    enabled  = false
  }
}

# Key Vault audit logs → private storage
resource "azurerm_monitor_diagnostic_setting" "kv_to_priv_logs" {
  count               = var.enable_storage_diagnostics_to_storage && length(azurerm_key_vault.kv) > 0 ? 1 : 0
  name                = "kv-to-priv-logs"
  target_resource_id  = azurerm_key_vault.kv[0].id
  storage_account_id  = azurerm_storage_account.private.id

  log {
    category = "AuditEvent"
    enabled  = true
  }

  metric {
    category = "AllMetrics"
    enabled  = false
  }
}
