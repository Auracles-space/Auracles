# Inputs for the Amplify Hosting module.

variable "app_name" {
  description = "Amplify app name, as shown in the console."
  type        = string
}

variable "repository_url" {
  description = "HTTPS URL of the GitHub repository Amplify builds from."
  type        = string
}

variable "github_access_token" {
  description = "GitHub personal access token with `repo` scope, used ONLY when Amplify first connects the repository — Amplify stores its own installation afterwards, so the token can be revoked once the app exists. Supply it via the TF_VAR_github_access_token environment variable rather than a tfvars file, so it never lands on disk or in state as an input. Terraform still records it in state, which is why the state bucket is private and encrypted."
  type        = string
  sensitive   = true
}

variable "branch_name" {
  description = "Git branch this app builds and serves. One branch per app keeps a broken feature branch from ever becoming a public URL against a live backend."
  type        = string
}

variable "stage" {
  description = "Amplify stage label for the branch: PRODUCTION, BETA, DEVELOPMENT, EXPERIMENTAL, or PULL_REQUEST. Cosmetic in the console, but it is what distinguishes environments at a glance."
  type        = string
  default     = "DEVELOPMENT"

  validation {
    condition = contains(
      ["PRODUCTION", "BETA", "DEVELOPMENT", "EXPERIMENTAL", "PULL_REQUEST"],
      var.stage,
    )
    error_message = "Stage must be one of PRODUCTION, BETA, DEVELOPMENT, EXPERIMENTAL, PULL_REQUEST."
  }
}

variable "environment_variables" {
  description = "App-wide build environment. NEXT_PUBLIC_* values are inlined into the client bundle by `next build`; server-side values additionally need forwarding in amplify.yml, because Amplify exposes these at build time only."
  type        = map(string)
  default     = {}
}

variable "branch_environment_variables" {
  description = "Branch-specific overrides, merged over the app-wide map by Amplify. The backend origin belongs here: it is what makes one branch staging and another production."
  type        = map(string)
  default     = {}
}

variable "custom_domain" {
  description = "Domain to serve the branch at, or null for the *.amplifyapp.com URL only. Must be a domain whose Route 53 zone lives in this account — Amplify writes its own validation and CNAME records. Attaching one blocks on certificate validation, so leave it null while iterating."
  type        = string
  default     = null
}
