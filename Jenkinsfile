pipeline {
    agent any

    triggers {
        pollSCM('H/2 * * * *')
    }

    parameters {
        booleanParam(name: 'DESTROY_AWS', defaultValue: false,
                     description: 'Delete all AWS resources created by this pipeline (then skip the cost gate and deployments)')
    }

    environment {
        ACR_NAME = 'cloudcostcicdacr'

        ARM_CLIENT_ID       = credentials('azure-client-id')
        ARM_CLIENT_SECRET   = credentials('azure-client-secret')
        ARM_TENANT_ID       = credentials('azure-tenant-id')
        ARM_SUBSCRIPTION_ID = credentials('azure-subscription-id')
        GCP_API_KEY         = credentials('gcp-api-key')

        AWS_ACCESS_KEY_ID     = credentials('aws-access-key-id')
        AWS_SECRET_ACCESS_KEY = credentials('aws-secret-access-key')
        AWS_DEFAULT_REGION    = 'ap-south-1'

        BUDGET = '50'
    }

    stages {

        stage('Install Dependencies') {
            steps {
                sh 'pip3 install -r requirements.txt --break-system-packages'
            }
        }

        stage('Dependency Check') {
            steps {
                sh 'pip3 install pip-audit --break-system-packages'
                sh 'python3 -m pip_audit || true'
            }
        }

        stage('Run Tests') {
            steps {
                sh 'python3 -m pytest test_app.py -v'
            }
        }

        stage('Build Docker Image') {
            steps {
                sh 'docker build -t myapp:${BUILD_NUMBER} .'
            }
        }

        stage('Azure Login') {
            steps {
                sh '''
                    az login \
                      --service-principal \
                      -u "$ARM_CLIENT_ID" \
                      -p "$ARM_CLIENT_SECRET" \
                      --tenant "$ARM_TENANT_ID"
                '''
            }
        }

        stage('Terraform Plan') {
            steps {
                dir('terraform-infra') {
                    sh '''
                        terraform init
                        terraform plan -out=tfplan
                        terraform show -json tfplan > plan.json
                    '''
                }
            }
        }

        stage('Cost Estimate') {
            steps {
                sh 'python3 csp-comparison/estimate.py terraform-infra/plan.json'
            }
        }

        stage('AWS Cleanup') {
            when {
                expression { params.DESTROY_AWS }
            }
            steps {
                sh '''
                    aws eks update-kubeconfig \
                      --region ${AWS_DEFAULT_REGION} \
                      --name cloud-cost-cicd-eks || true

                    kubectl delete service myapp-service --ignore-not-found --timeout=120s || true
                    sleep 60
                '''
                dir('terraform-aws') {
                    sh '''
                        terraform init
                        terraform destroy -auto-approve
                    '''
                }
            }
        }

        stage('Cloud Cost Gate') {
            when {
                expression { !params.DESTROY_AWS }
            }
            steps {
                script {
                    sh 'chmod +x csp-comparison/cost-gate.sh'

                    def result = sh(
                        script: 'BUDGET=$BUDGET ./csp-comparison/cost-gate.sh',
                        returnStdout: true
                    ).trim()

                    echo result

                    if (result.contains('WITHIN_BUDGET')) {
                        env.SELECTED_CSP = 'Azure'
                        echo 'Cost is within budget. Continuing with Azure deployment.'
                    } else {
                        def selected = 'STOP'

                        timeout(time: 30, unit: 'MINUTES') {
                            selected = input(
                                message: 'Azure is over budget. Select deployment option:',
                                parameters: [
                                    choice(
                                        name: 'CSP',
                                        choices: 'Azure\nAWS\nGCP\nSTOP',
                                        description: 'Select the cloud provider to deploy'
                                    )
                                ]
                            )
                        }

                        env.SELECTED_CSP = selected

                        if (selected == 'STOP') {
                            error('Deployment stopped by user.')
                        }

                        echo "Selected CSP: ${selected}"

                        if (selected == 'GCP') {
                            error('GCP cost comparison is available, but GCP deployment is not configured.')
                        }
                    }
                }
            }
        }

        // ---------------- Azure ----------------

        stage('Terraform Apply - Azure') {
            when {
                expression { env.SELECTED_CSP == 'Azure' }
            }
            steps {
                dir('terraform-infra') {
                    sh 'terraform apply -auto-approve tfplan'
                }
            }
        }

        stage('Push to ACR') {
            when {
                expression { env.SELECTED_CSP == 'Azure' }
            }
            steps {
                sh '''
                    az acr login --name "$ACR_NAME"

                    docker tag myapp:${BUILD_NUMBER} \
                      ${ACR_NAME}.azurecr.io/myapp:${BUILD_NUMBER}

                    docker tag myapp:${BUILD_NUMBER} \
                      ${ACR_NAME}.azurecr.io/myapp:latest
                '''
                retry(3) {
                    sh 'docker push ${ACR_NAME}.azurecr.io/myapp:${BUILD_NUMBER}'
                }
                retry(3) {
                    sh 'docker push ${ACR_NAME}.azurecr.io/myapp:latest'
                }
            }
        }

        stage('Deploy to AKS') {
            when {
                expression { env.SELECTED_CSP == 'Azure' }
            }
            steps {
                sh '''
                    az aks get-credentials \
                      --resource-group cloud-cost-cicd-rg \
                      --name cloud-cost-cicd-aks \
                      --overwrite-existing

                    kubectl set image \
                      deployment/myapp-deployment \
                      myapp=${ACR_NAME}.azurecr.io/myapp:${BUILD_NUMBER} \
                      || kubectl apply -f deployment.yaml

                    kubectl rollout status deployment/myapp-deployment
                '''
            }
        }

        // ---------------- AWS ----------------

        stage('Terraform Apply - AWS') {
            when {
                expression { env.SELECTED_CSP == 'AWS' }
            }
            steps {
                dir('terraform-aws') {
                    sh '''
                        terraform init
                        terraform apply -auto-approve
                    '''
                }
            }
        }

        stage('Push to ECR') {
            when {
                expression { env.SELECTED_CSP == 'AWS' }
            }
            steps {
                script {
                    env.ECR_REGISTRY = sh(
                        script: 'echo $(aws sts get-caller-identity --query Account --output text).dkr.ecr.${AWS_DEFAULT_REGION}.amazonaws.com',
                        returnStdout: true
                    ).trim()
                }
                sh '''
                    aws ecr get-login-password --region ${AWS_DEFAULT_REGION} \
                      | docker login --username AWS --password-stdin ${ECR_REGISTRY}

                    docker tag myapp:${BUILD_NUMBER} ${ECR_REGISTRY}/myapp:${BUILD_NUMBER}
                    docker tag myapp:${BUILD_NUMBER} ${ECR_REGISTRY}/myapp:latest
                '''
                retry(3) {
                    sh 'docker push ${ECR_REGISTRY}/myapp:${BUILD_NUMBER}'
                }
                retry(3) {
                    sh 'docker push ${ECR_REGISTRY}/myapp:latest'
                }
            }
        }

        stage('Deploy to EKS') {
            when {
                expression { env.SELECTED_CSP == 'AWS' }
            }
            steps {
                sh '''
                    aws eks update-kubeconfig \
                      --region ${AWS_DEFAULT_REGION} \
                      --name cloud-cost-cicd-eks

                    sed "s|image: .*|image: ${ECR_REGISTRY}/myapp:${BUILD_NUMBER}|" deployment.yaml \
                      | kubectl apply -f -

                    kubectl rollout status deployment/myapp-deployment --timeout=300s
                '''
            }
        }
    }

    post {
        always {
            echo "Selected CSP: ${env.SELECTED_CSP ?: 'NONE'}"
        }
        success {
            echo '===== PIPELINE COMPLETED SUCCESSFULLY ====='
        }
        failure {
            echo '===== PIPELINE FAILED / STOPPED ====='
        }
    }
}