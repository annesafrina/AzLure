variable "project_name" {
  type    = string
  default = "azlure"
}

variable "location" {
  type    = string
  default = "southeastasia"
}

variable "tenant_domain" {
  type    = string
  default = "secureorg.onmicrosoft.com"
}

variable "resource_group" {
  type    = string
  default = "azlure-rg"
}

variable "public_storage_account_name" {
  type    = string
  default = "secureorgbackup"
}

variable "private_storage_account_name" {
  type    = string
  default = "secureorgpriv"
}

variable "public_container_name" {
  type    = string
  default = "backup"
}

variable "private_container_name" {
  type    = string
  default = "secrets"
}

variable "key_vault_name" {
  type    = string
  default = "kv-azlure"
}

variable "automation_account_name" {
  description = "Automation Account name"
  type        = string
  #default     = "automatic-backup"
}

variable "randomize_names" {
  type    = bool
  default = true
}

variable "enable_log_analytics" {
  type    = bool
  default = false
}

variable "create_key_vault" {
  type    = bool
  default = true
}

variable "create_automation_account" {
  type    = bool
  default = true
}

variable "create_app_registration" {
  type    = bool
  default = true
}

variable "grant_app_reader_on_rg" {
  type    = bool
  default = true
}

variable "grant_app_kv_secrets_user" {
  type    = bool
  default = true
}

variable "grant_app_automation_contributor" {
  type    = bool
  default = true
}

#variable "enable_storage_diagnostics_to_storage" {
#  type    = bool
#  default = false
#}
