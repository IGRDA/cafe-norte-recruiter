output "state_bucket" {
  value = google_storage_bucket.state.name
}

output "workload_identity_provider" {
  value       = google_iam_workload_identity_pool_provider.github.name
  description = "Copied into the GitHub Actions variable GCP_WORKLOAD_IDENTITY_PROVIDER."
}

output "deployer_service_account" {
  value       = google_service_account.deployer.email
  description = "Copied into the GitHub Actions variable GCP_DEPLOYER_SERVICE_ACCOUNT."
}

output "project_number" {
  value = data.google_project.this.number
}
