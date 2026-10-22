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
  description = "A free DNS name with an A record on the static address, e.g. cafenorte-recruiting.duckdns.org. Empty serves only the sslip.io name."
}
variable "db_tier" {
  type        = string
  default     = "db-f1-micro"
  description = "Shared-core Postgres 16: about 8 EUR a month; enough for a demo of about ten testers."
}
variable "db_name" {
  type    = string
  default = "cafe_norte"
}
variable "db_user" {
  type        = string
  default     = "cafe_norte"
  description = "One built-in user owns the schema and serves the app; roles split later."
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
  description = "Ana's ElevenLabs voice, Spanish and English alike."
}

variable "enable_database" {
  type        = bool
  default     = true
  description = "Cloud SQL and the Auth Proxy on the VM; false keeps the memory store."
}

variable "machine_type" {
  type        = string
  default     = "e2-standard-4"
  description = "One VM runs the app and Caddy. e2-standard-4 (4 vCPU, 16 GB) carries max_voice_sessions calls beside the text chats; e2-small carries two calls."
}

variable "max_voice_sessions" {
  type        = number
  default     = 6
  description = "CAFE_NORTE_MAX_VOICE_SESSIONS: simultaneous calls, counted across every instance on the database. Each call is a CPU-bound pipeline on this VM and one ElevenLabs request at a time, so keep it within both."
}

variable "session_starts_per_hour" {
  type        = number
  default     = 30
  description = "CAFE_NORTE_SESSION_STARTS_PER_HOUR per client IP. Testers in one office share an IP; the daily session ceiling still bounds spend."
}

variable "db_pool_size" {
  type        = number
  default     = 10
  description = "CAFE_NORTE_DB_POOL_SIZE: a turn, a stream poll and a heartbeat each need a connection. Ten stays well below db-f1-micro's connection limit."
}

variable "signal_model" {
  type        = string
  default     = "openrouter/typesafe/jev-1.14"
  description = "CAFE_NORTE_SIGNAL_MODEL for the hosted demo: Jev reads sentiment and the language switch beside the turn; fictional data only. Empty turns the analyzer off."
}

variable "langfuse_base_url" {
  type        = string
  default     = "https://cloud.langfuse.com"
  description = "Langfuse host for traces (EU cloud); the keys are secrets, not variables."
}
