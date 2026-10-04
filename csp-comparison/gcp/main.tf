terraform {
  required_providers {
    google = {
      source  = "hashicorp/google"
      version = "~> 6.0"
    }
  }
}

provider "google" {
  project = "cloud-cost-cicd"
  region  = "asia-south1"
}

# Equivalent of Azure ACR / AWS ECR
resource "google_artifact_registry_repository" "app" {
  location      = "asia-south1"
  repository_id = "cloud-cost-cicd"
  format        = "DOCKER"
}

# GKE control plane
resource "google_container_cluster" "app" {
  name     = "cloud-cost-cicd-gke"
  location = "asia-south1"

  initial_node_count = 1

  node_config {
    machine_type = "e2-standard-2"
  }
}