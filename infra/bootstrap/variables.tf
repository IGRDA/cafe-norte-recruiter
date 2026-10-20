variable "project_id" {
  type        = string
  description = "Dedicated demo project under the existing billing account. Never inferred."
}

variable "region" {
  type    = string
  default = "europe-west1"
}

variable "github_repository" {
  type        = string
  description = "owner/name allowed to deploy through Workload Identity Federation."
}

variable "state_bucket_name" {
  type = string
}
