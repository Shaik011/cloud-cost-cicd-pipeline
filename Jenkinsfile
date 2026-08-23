pipeline {
    agent any
    environment {
        DOCKERHUB_CREDENTIALS = credentials('dockerhub-creds')
    }
    stages {
        stage('Build') {
            steps {
                sh 'docker build -t shaik011/myapp:${BUILD_NUMBER} .'
            }
        }
        stage('Push') {
            steps {
                sh 'echo $DOCKERHUB_CREDENTIALS_PSW | docker login -u $DOCKERHUB_CREDENTIALS_USR --password-stdin'
                sh 'docker push shaik011/myapp:${BUILD_NUMBER}'
            }
        }
    }
}