pipeline {
    agent any
    environment {
        ACR_NAME = 'cloudcostcicdacr'
        ARM_CLIENT_ID       = credentials('azure-client-id')
        ARM_CLIENT_SECRET   = credentials('azure-client-secret')
        ARM_TENANT_ID       = credentials('azure-tenant-id')
        ARM_SUBSCRIPTION_ID = credentials('azure-subscription-id')
    }
    stages {
        stage('Install Dependencies') {
            steps {
                sh 'pip3 install -r requirements.txt --break-system-packages'
            }
        }
        stage('Dependency Check') {
            steps {
                sh 'pip3 install pip-audit --break-system-packages || true'
                sh 'python3 -m pip_audit -r requirements.txt || true'
            }
        }
        stage('Run Tests') {
            steps {
                sh 'python3 -m pytest test_app.py -v'
            }
        }
        stage('Build') {
            steps {
                sh 'docker build -t myapp:${BUILD_NUMBER} .'
            }
        }
        stage('Azure Login') {
            steps {
                sh 'az login --service-principal -u $ARM_CLIENT_ID -p $ARM_CLIENT_SECRET --tenant $ARM_TENANT_ID'
            }
        }
        stage('Terraform Apply') {
            steps {
                dir('terraform-infra') {
                    sh 'terraform init'
                    sh 'terraform apply -auto-approve'
                }
            }
        }
        stage('Push to ACR') {
            steps {
                sh 'az acr login --name ${ACR_NAME}'
                sh 'docker tag myapp:${BUILD_NUMBER} ${ACR_NAME}.azurecr.io/myapp:${BUILD_NUMBER}'
                sh 'docker tag myapp:${BUILD_NUMBER} ${ACR_NAME}.azurecr.io/myapp:latest'
                sh 'docker push ${ACR_NAME}.azurecr.io/myapp:${BUILD_NUMBER}'
                sh 'docker push ${ACR_NAME}.azurecr.io/myapp:latest'
            }
        }
        stage('Deploy to Kubernetes') {
            steps {
                sh 'az aks get-credentials --resource-group cloud-cost-cicd-rg --name cloud-cost-cicd-aks --overwrite-existing'
                sh 'kubectl set image deployment/myapp-deployment myapp=${ACR_NAME}.azurecr.io/myapp:${BUILD_NUMBER} --record || kubectl apply -f deployment.yaml'
            }
        }
    }
}