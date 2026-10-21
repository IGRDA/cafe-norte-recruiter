output "service_url" {
  value       = google_cloud_run_v2_service.app.uri
  description = "The managed run.app URL; no custom domain for the demo."
}

output "artifact_repository" {
  value = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.app.repository_id}"
}

output "runtime_service_account" {
  value = google_service_account.runtime.email
}
