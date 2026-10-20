variable "project_id" { type = string }
variable "region" {
  type    = string
  default = "europe-west1"
}
variable "service_name" {
  type    = string
  default = "cafe-norte"
}
variable "image_digest" {
  type        = string
  description = "Full image reference with digest, e.g. europe-west1-docker.pkg.dev/p/r/app@sha256:..."
}
variable "min_instances" {
  type    = number
  default = 1
}
variable "max_instances" {
  type    = number
  default = 1
}
variable "cpu" {
  type    = string
  default = "1"
}
variable "memory" {
  type    = string
  default = "2Gi"
}
variable "db_tier" {
  type    = string
  default = "db-g1-small"
}
variable "budget_eur" {
  type    = number
  default = 30
}
variable "billing_account" { type = string }
variable "demo_end_date" {
  type        = string
  description = "ISO date after which the stack is torn down; recorded as a label."
}
