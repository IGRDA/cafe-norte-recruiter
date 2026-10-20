# bootstrap stack

Run once with local Application Default Credentials. Creates the state bucket, the GitHub
Workload Identity Federation pool/provider restricted to this repository and the `main`
branch, and the deployer service account that CI impersonates. No long-lived keys.
