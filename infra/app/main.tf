# Everything the running demo needs. The image is an input (image_digest), so a deployment is a
# Terraform change. Cloud SQL and the uptime check arrive with their stages (enable_database).

provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true # user-credential calls (budgets) bill their quota to this project
  billing_project       = var.project_id
}

locals {
  secret_names = [
    "OPENAI_API_KEY",
    "GROQ_API_KEY",
    "DAILY_API_KEY",
    "DEEPGRAM_API_KEY",
    "ELEVENLABS_API_KEY",
    "CAFE_NORTE_ACCESS_CODE",
    "CAFE_NORTE_COOKIE_SECRET",
  ]
}

resource "google_artifact_registry_repository" "app" {
  repository_id = "app"
  format        = "DOCKER"
  location      = var.region
  description   = "Café Norte images, deployed by digest"
}

resource "google_service_account" "runtime" {
  account_id   = "cafe-norte-runtime"
  display_name = "Cloud Run runtime: secrets and logs only"
}

resource "google_project_iam_member" "runtime_logs" {
  project = var.project_id
  role    = "roles/logging.logWriter"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

# Secrets exist by name; versions are added by scripts/set_secrets.py, never by Terraform.
resource "google_secret_manager_secret" "keys" {
  for_each  = toset(local.secret_names)
  secret_id = each.value

  replication {
    auto {}
  }
}

resource "google_secret_manager_secret_iam_member" "runtime_reads" {
  for_each  = google_secret_manager_secret.keys
  secret_id = each.value.id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_cloud_run_v2_service" "app" {
  name                = var.service_name
  location            = var.region
  ingress             = "INGRESS_TRAFFIC_ALL"
  deletion_protection = false

  template {
    service_account                  = google_service_account.runtime.email
    timeout                          = "600s"
    max_instance_request_concurrency = 20
    session_affinity                 = true
    execution_environment            = "EXECUTION_ENVIRONMENT_GEN2"

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.image_digest

      resources {
        limits            = { cpu = var.cpu, memory = var.memory }
        cpu_idle          = false # CPU always allocated: voice tasks run between requests
        startup_cpu_boost = true
      }

      ports {
        container_port = 8080
      }

      env {
        name  = "CAFE_NORTE_ENV"
        value = "demo"
      }
      env {
        name  = "CAFE_NORTE_MODEL"
        value = var.model
      }
      env {
        name  = "CAFE_NORTE_VOICE"
        value = "pipecat"
      }
      env {
        name  = "ELEVENLABS_VOICE_ID"
        value = var.elevenlabs_voice_id
      }
      env {
        name  = "CAFE_NORTE_MAX_VOICE_SESSIONS"
        value = "2"
      }
      dynamic "env" {
        for_each = toset(local.secret_names)
        content {
          name = env.value
          value_source {
            secret_key_ref {
              secret  = google_secret_manager_secret.keys[env.value].secret_id
              version = "latest"
            }
          }
        }
      }

      startup_probe {
        http_get {
          path = "/health/ready"
        }
        initial_delay_seconds = 5
        period_seconds        = 5
        failure_threshold     = 12
      }
      liveness_probe {
        http_get {
          path = "/health/live"
        }
        period_seconds = 30
      }
    }
  }

  depends_on = [google_secret_manager_secret_iam_member.runtime_reads]

  lifecycle {
    # The API fills service-level scaling defaults the provider then wants to remove.
    ignore_changes = [scaling]
  }
}

# The page is public; the app enforces the shared access code.
resource "google_cloud_run_v2_service_iam_member" "public" {
  name     = google_cloud_run_v2_service.app.name
  location = var.region
  role     = "roles/run.invoker"
  member   = "allUsers"
}

data "google_project" "this" {
  project_id = var.project_id
}
