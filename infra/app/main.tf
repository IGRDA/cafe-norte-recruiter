# Deploy the image digest on Compute Engine: Daily WebRTC needs a routable network
# interface, unavailable in the tested Cloud Run environment. The VM runs the app, Caddy
# and Cloud SQL Auth Proxy with host networking; see infra/OPERATIONS.md.

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
    "LANGFUSE_PUBLIC_KEY", # tracing; empty until set_secrets.py --only writes a version
    "LANGFUSE_SECRET_KEY",
    "OPENROUTER_API_KEY", # Jev signal analyzer; a version must exist before it is enabled
  ]
}

# OPENROUTER_API_KEY was created with its first version before Terraform knew it, so the first
# deploy with the analyzer on found a key (an analyzer without one refuses to start).
import {
  to = google_secret_manager_secret.keys["OPENROUTER_API_KEY"]
  id = "projects/${var.project_id}/secrets/OPENROUTER_API_KEY"
}

resource "google_artifact_registry_repository" "app" {
  repository_id = "app"
  format        = "DOCKER"
  location      = var.region
  description   = "Café Norte images, deployed by digest"
}

resource "google_service_account" "runtime" {
  account_id   = "cafe-norte-runtime"
  display_name = "VM runtime: secrets, images and logs only"
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

# One small VM instead of Cloud Run: Cloud Run containers only have a link-local address and
# libwebrtc (daily-core) cannot gather ICE candidates there, so no voice media ever flows.
resource "google_compute_address" "app" {
  name   = "${var.service_name}-ip"
  region = var.region
}

locals {
  sslip_host = "${replace(google_compute_address.app.address, ".", "-")}.sslip.io"
  # The named host (DuckDNS) when set; the sslip.io name always answers too, as a fallback.
  public_host  = coalesce(var.public_hostname, local.sslip_host)
  public_hosts = distinct(compact([var.public_hostname, local.sslip_host]))
  plain_env = join("\n", [
    "CAFE_NORTE_ENV=demo",
    "CAFE_NORTE_MODEL=${var.model}",
    "CAFE_NORTE_SIGNAL_MODEL=${var.signal_model}", # empty: no analyzer
    "CAFE_NORTE_VOICE=pipecat",
    "ELEVENLABS_VOICE_ID=${var.elevenlabs_voice_id}",
    "CAFE_NORTE_MAX_VOICE_SESSIONS=2",
    "CAFE_NORTE_ENVIRONMENT=production",
    "CAFE_NORTE_TRACE_CONTENT=on", # redacted words and tool arguments in traces; fictional data only
    "LANGFUSE_BASE_URL=${var.langfuse_base_url}",
  ])
}

resource "google_compute_firewall" "web" {
  name          = "${var.service_name}-web"
  network       = "default"
  direction     = "INGRESS"
  source_ranges = ["0.0.0.0/0"]
  target_tags   = [var.service_name]

  allow {
    protocol = "tcp"
    ports    = ["80", "443"]
  }
}

data "google_compute_image" "cos" {
  family  = "cos-stable"
  project = "cos-cloud"
}

resource "google_compute_instance" "app" {
  name                      = var.service_name
  machine_type              = var.machine_type
  zone                      = "${var.region}-b"
  tags                      = [var.service_name]
  allow_stopping_for_update = true

  boot_disk {
    initialize_params {
      image = data.google_compute_image.cos.self_link
      size  = 20
    }
  }

  network_interface {
    network = "default"
    access_config {
      nat_ip = google_compute_address.app.address
    }
  }

  service_account {
    email  = google_service_account.runtime.email
    scopes = ["cloud-platform"]
  }

  metadata = {
    image                  = var.image_digest
    public_hosts           = join(" ", local.public_hosts)
    env                    = local.plain_env
    secret_names           = join(" ", concat(local.secret_names, var.enable_database ? [local.db_secret_name] : []))
    db_connection_name     = local.db_connection_name
    db_user                = var.db_user
    db_name                = var.db_name
    google-logging-enabled = "true"
  }
  metadata_startup_script = file("${path.module}/startup.sh")

  labels = {
    demo_end_date = replace(var.demo_end_date, "-", "_")
  }

  depends_on = [
    google_secret_manager_secret_iam_member.runtime_reads,
    google_secret_manager_secret_iam_member.runtime_reads_db_password,
  ]
}

resource "google_project_iam_member" "runtime_pulls_images" {
  project = var.project_id
  role    = "roles/artifactregistry.reader"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

data "google_project" "this" {
  project_id = var.project_id
}
