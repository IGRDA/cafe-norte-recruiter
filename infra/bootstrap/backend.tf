terraform {
  backend "gcs" {
    # bucket and prefix are given on `init -migrate-state` by scripts/ops/bootstrap.sh
  }
}
