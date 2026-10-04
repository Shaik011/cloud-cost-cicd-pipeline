terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

provider "aws" {
  region = "ap-south-1"
}

# Equivalent of Azure ACR
resource "aws_ecr_repository" "app" {
  name = "cloud-cost-cicd"
}

# Equivalent of Azure AKS control plane
resource "aws_eks_cluster" "app" {
  name = "cloud-cost-cicd-eks"

  vpc_config {
    subnet_ids = []
  }
}

# Cost-equivalent worker node:
# Azure Standard_B2s_v2 ≈ 2 vCPU / 8 GiB
# AWS t3.large = 2 vCPU / 8 GiB
resource "aws_instance" "worker" {
  instance_type = "t3.large"
}