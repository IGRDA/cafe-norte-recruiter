output "state_bucket" {
  value = var.state_bucket_name
}

output "workload_identity_provider" {
  value       = "projects/<number>/locations/global/workloadIdentityPools/github/providers/github"
  description = "Placeholder until the pool exists; copied into the GitHub Actions variables."
}
