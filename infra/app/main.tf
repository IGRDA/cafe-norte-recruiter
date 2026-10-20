# Resources (filled in at the bootstrap stage; names are the contract):
#   google_project_service.*                 run, sqladmin, artifactregistry, secretmanager, monitoring, logging
#   google_service_account.runtime           Secret accessor (named versions), Cloud SQL client, log writer
#   google_service_account.migrator          Cloud SQL client with the privileged database role
#   google_artifact_registry_repository.app  one regional Docker repository
#   google_secret_manager_secret.*           GROQ, DAILY, DEEPGRAM, ELEVENLABS, LANGFUSE_*, ACCESS_CODE, DB passwords
#   google_sql_database_instance.pg          POSTGRES_16, var.db_tier, zonal, 10 GiB SSD, 3 backups, no authorized networks
#   google_sql_database.app / google_sql_user.app, google_sql_user.migrator
#   google_cloud_run_v2_service.app          gen2, cpu always allocated, min/max instances, concurrency 20,
#                                            timeout 600 s, session affinity, startup probe /health/ready,
#                                            liveness probe /health/live, Cloud SQL volume, secrets by version
#   google_cloud_run_v2_service_iam_member   allUsers invoker (app enforces access)
#   google_monitoring_uptime_check_config    GET /health/live
#   google_monitoring_alert_policy           sustained 5xx
#   google_billing_budget.demo               var.budget_eur with 50/80/100 % thresholds
provider "google" {
  project = var.project_id
  region  = var.region
}
