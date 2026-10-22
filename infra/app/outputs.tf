output "service_url" {
  value       = "https://${local.public_host}"
  description = "The named host when public_hostname is set, else the sslip.io name; Caddy serves both with TLS."
}

output "instance" {
  value = "${google_compute_instance.app.name} (${google_compute_instance.app.zone})"
}

output "artifact_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}

output "database_connection_name" {
  value       = local.db_connection_name
  description = "project:region:instance for the Auth Proxy; empty when the database is disabled."
}
