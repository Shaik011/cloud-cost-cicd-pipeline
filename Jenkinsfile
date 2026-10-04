pipeline {
    agent any

    environment {
        ACR_NAME = 'cloudcostcicdacr'

        ARM_CLIENT_ID       = credentials('azure-client-id')
        ARM_CLIENT_SECRET   = credentials('azure-client-secret')
        ARM_TENANT_ID       = credentials('azure-tenant-id')
        ARM_SUBSCRIPTION_ID = credentials('azure-subscription-id')

        INFRACOST_CLI_AUTHENTICATION_TOKEN = credentials('infracost-api-token')

        BUDGET = '80'
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
                    '''
                }
            }
        }

        stage('Infracost Scan') {
            steps {
                sh '''
                    echo "===== RUNNING INFRACOST ====="
                    infracost auth whoami
                    infracost scan terraform-infra --json > terraform-infra/cost.json
                    infracost inspect --file terraform-infra/cost.json --summary

                    echo "===== AZURE ESTIMATED COST ====="
                    python3 csp-comparison/get_cost.py terraform-infra/cost.json
                '''
            }
        }

        stage('Cloud Cost Gate') {
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
                        def choice = 'STOP'

                        timeout(time: 30, unit: 'MINUTES') {
                            choice = input(
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

                        env.SELECTED_CSP = choice

                        if (choice == 'STOP') {
                            error('Deployment stopped by user.')
                        }

                        echo "Selected CSP: ${choice}"

                        if (choice == 'AWS') {
                            error('AWS cost comparison is available, but AWS deployment is not configured yet.')
                        }

                        if (choice == 'GCP') {
                            error('GCP cost comparison is available, but GCP deployment is not configured yet.')
                        }
                    }
                }
            }
        }

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

                    docker push ${ACR_NAME}.azurecr.io/myapp:${BUILD_NUMBER}
                    docker push ${ACR_NAME}.azurecr.io/myapp:latest
                '''
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