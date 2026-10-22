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
variable "public_hostname" {
  type        = string
  default     = ""
  description = "A free DNS name with an A record on the static address, e.g. cafenorte-recruiting.duckdns.org (D60). Empty serves only the sslip.io name."
}
variable "db_tier" {
  type        = string
  default     = "db-f1-micro"
  description = "Shared-core Postgres 16: about 8 EUR a month; two voice sessions never need more."
}
variable "db_name" {
  type    = string
  default = "cafe_norte"
}
variable "db_user" {
  type        = string
  default     = "cafe_norte"
  description = "One built-in user owns the schema and serves the app (D33); roles split later."
}
variable "db_password_version" {
  type        = number
  default     = 1
  description = "Bump to rotate the generated database password (user and Secret Manager together)."
}
variable "demo_end_date" {
  type        = string
  description = "ISO date after which the stack is torn down; recorded as a label."
}

variable "model" {
  type        = string
  default     = "openai/gpt-4.1"
  description = "CAFE_NORTE_MODEL for the hosted demo; Groq's free tier is too small for a shared URL."
}

variable "elevenlabs_voice_id" {
  type        = string
  default     = "uQw4jpKzMLrZuo0RLPS9"
  description = "Ana's ElevenLabs voice, Spanish and English alike (D47)."
}

variable "enable_database" {
  type        = bool
  default     = true
  description = "Cloud SQL and the Auth Proxy on the VM (D33); false keeps the memory store."
}

variable "machine_type" {
  type        = string
  default     = "e2-small"
  description = "One VM runs the app and Caddy; e2-small is enough for two voice sessions."
}

variable "signal_model" {
  type        = string
  default     = "openrouter/typesafe/jev-1.14"
  description = "CAFE_NORTE_SIGNAL_MODEL for the hosted demo: Jev reads sentiment and the language switch beside the turn (D52); fictional data only. Empty turns the analyzer off."
}

variable "langfuse_base_url" {
  type        = string
  default     = "https://cloud.langfuse.com"
  description = "Langfuse host for traces (EU cloud, D05); the keys are secrets, not variables."
}
