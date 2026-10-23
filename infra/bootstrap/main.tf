# Run once with local Application Default Credentials (scripts/ops/bootstrap.sh). Creates the
# Terraform state bucket, the GitHub Workload Identity Federation pool and provider restricted
# to this repository's main branch, and the deployer service account CI impersonates. No keys.

provider "google" {
  project               = var.project_id
  region                = var.region
  user_project_override = true # user-credential calls (budgets) bill their quota to this project
  billing_project       = var.project_id
}

data "google_project" "this" {
  project_id = var.project_id
}

resource "google_storage_bucket" "state" {
  name                        = var.state_bucket_name
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }
}

resource "google_iam_workload_identity_pool" "github" {
  workload_identity_pool_id = "github"
  display_name              = "GitHub Actions"
}

resource "google_iam_workload_identity_pool_provider" "github" {
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = "github"
  display_name                       = "GitHub OIDC"

  attribute_mapping = {
    "google.subject"       = "assertion.sub"
    "attribute.repository" = "assertion.repository"
    "attribute.ref"        = "assertion.ref"
  }
  # Only this repository, only its main branch, may mint deployer credentials.
  attribute_condition = "assertion.repository == \"${var.github_repository}\" && assertion.ref == \"refs/heads/main\""

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account" "deployer" {
  account_id   = "deployer"
  display_name = "CI deployer (GitHub Actions through WIF)"
}

resource "google_service_account_iam_member" "deployer_wif" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

# Deploy permissions only: push images, manage the VM, read secrets' names,
# act as the runtime service account, keep Terraform state.
resource "google_project_iam_member" "deployer" {
  for_each = toset([
    "roles/compute.admin",
    "roles/cloudsql.admin", # database.tf in the app stack
    "roles/artifactregistry.writer",
    "roles/secretmanager.admin",
    "roles/iam.serviceAccountUser",
    "roles/iam.serviceAccountAdmin",
    "roles/resourcemanager.projectIamAdmin",
    "roles/serviceusage.serviceUsageAdmin",
    "roles/logging.viewer",
  ])
  project = var.project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_storage_bucket_iam_member" "deployer_state" {
  bucket = google_storage_bucket.state.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.deployer.email}"
}

# The budget lives here, applied once by a person: the CI deployer has no billing-account
# permissions and must not need them.
resource "google_billing_budget" "demo" {
  billing_account = var.billing_account
  display_name    = "cafe-norte demo"

  budget_filter {
    projects = ["projects/${data.google_project.this.number}"]
  }

  amount {
    specified_amount {
      currency_code = "EUR"
      units         = tostring(var.budget_eur)
    }
  }

  dynamic "threshold_rules" {
    for_each = [0.5, 0.8, 1.0]
    content {
      threshold_percent = threshold_rules.value
    }
  }
}
