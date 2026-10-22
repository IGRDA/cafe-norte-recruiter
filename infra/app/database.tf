# Cloud SQL for the demo: the smallest Postgres 16 instance, reached from the VM through
# the Cloud SQL Auth Proxy (IAM identity of the runtime service account, no authorized
# networks). The runtime user's password is generated here as an ephemeral value and written
# only to places Terraform does not read back: the user (`password_wo`) and a Secret Manager
# version (`secret_data_wo`). It never enters the plan or the state. Bump
# `db_password_version` to rotate it; the VM reads it at boot like every other secret.

resource "google_project_service" "sqladmin" {
  service            = "sqladmin.googleapis.com"
  disable_on_destroy = false
}

resource "google_sql_database_instance" "db" {
  count               = var.enable_database ? 1 : 0
  name                = "${var.service_name}-db"
  database_version    = "POSTGRES_16"
  region              = var.region
  deletion_protection = false # the demo is torn down by scripts/teardown.sh

  settings {
    tier              = var.db_tier
    edition           = "ENTERPRISE"
    availability_type = "ZONAL"
    disk_type         = "PD_HDD" # a demo of about ten testers; nothing here needs an SSD
    disk_size         = 10
    disk_autoresize   = false

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = false
      backup_retention_settings {
        retained_backups = 3 # deleted records leave the backups within days
        retention_unit   = "COUNT"
      }
    }

    ip_configuration {
      ipv4_enabled = true # no authorized networks: only the Auth Proxy, with IAM, gets in
    }

    user_labels = {
      demo_end_date = replace(var.demo_end_date, "-", "_")
    }
  }

  depends_on = [google_project_service.sqladmin]
}

resource "google_sql_database" "app" {
  count    = var.enable_database ? 1 : 0
  name     = var.db_name
  instance = google_sql_database_instance.db[0].name
}

ephemeral "random_password" "db" {
  length  = 32
  special = false # the password sits inside a connection URL; no escaping to get wrong
}

resource "google_sql_user" "runtime" {
  count               = var.enable_database ? 1 : 0
  name                = var.db_user
  instance            = google_sql_database_instance.db[0].name
  type                = "BUILT_IN"
  password_wo         = ephemeral.random_password.db.result
  password_wo_version = var.db_password_version
  deletion_policy     = "ABANDON" # Postgres refuses to drop a user that owns objects
}

resource "google_secret_manager_secret" "db_password" {
  count     = var.enable_database ? 1 : 0
  secret_id = local.db_secret_name

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_version" "db_password" {
  count                  = var.enable_database ? 1 : 0
  secret                 = google_secret_manager_secret.db_password[0].id
  secret_data_wo         = ephemeral.random_password.db.result
  secret_data_wo_version = var.db_password_version
}

resource "google_secret_manager_secret_iam_member" "runtime_reads_db_password" {
  count     = var.enable_database ? 1 : 0
  secret_id = google_secret_manager_secret.db_password[0].id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

# The Auth Proxy on the VM authenticates as the runtime service account.
resource "google_project_iam_member" "runtime_sql_client" {
  project = var.project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

locals {
  db_secret_name     = "CAFE_NORTE_DB_PASSWORD"
  db_connection_name = var.enable_database ? google_sql_database_instance.db[0].connection_name : ""
}
