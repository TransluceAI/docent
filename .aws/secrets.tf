# 1Password secrets
# All items are in the "Shared" vault with prefix "docent-"

data "onepassword_item" "db_password" {
  vault = "Shared"
  title = "docent-${var.deployment}-db"
}

data "onepassword_item" "tailscale_auth_key" {
  vault = "Shared"
  title = "docent-${var.deployment}-tailscale-auth-key"
}

data "onepassword_item" "datadog_api_key" {
  vault = "Shared"
  title = "docent-ddog-api-key"
}

data "onepassword_item" "datadog_app_key" {
  vault = "Shared"
  title = "docent-ddog-app-key"
}

data "onepassword_item" "tailscale_oauth_client_id" {
  vault = "Shared"
  title = "docent-tailscale-oauth-client-id"
}

data "onepassword_item" "tailscale_oauth_client_secret" {
  vault = "Shared"
  title = "docent-tailscale-oauth-client-secret"
}

locals {
  db_password                   = data.onepassword_item.db_password.password
  tailscale_auth_key            = data.onepassword_item.tailscale_auth_key.credential
  tailscale_oauth_client_id     = data.onepassword_item.tailscale_oauth_client_id.credential
  tailscale_oauth_client_secret = data.onepassword_item.tailscale_oauth_client_secret.credential
  datadog_api_key               = data.onepassword_item.datadog_api_key.credential
  datadog_app_key               = data.onepassword_item.datadog_app_key.credential
}
