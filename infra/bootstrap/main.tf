# Resources (filled in at the bootstrap stage):
#   google_storage_bucket.state            versioning on, uniform access, public access prevention
#   google_iam_workload_identity_pool.ci   + provider restricted to var.github_repository, refs/heads/main
#   google_service_account.deployer        impersonated by GitHub Actions; deploy permissions only
#   google_project_iam_member.*            Cloud Run admin, Artifact Registry writer, Cloud SQL client,
#                                          Secret Manager accessor for the deployer; nothing for runtime
provider "google" {
  project = var.project_id
  region  = var.region
}
