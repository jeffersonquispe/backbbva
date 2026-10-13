#!groovy

// Project vars
TRACE="TRACE"
jobName = env.JOB_NAME
jobNameParts = jobName.split('/')
BITBUCKET_PROJECT = jobNameParts[0]

@Library('genai@v1.15.0') _
@Library('sonar') l2

def node_label = "Genai-${BITBUCKET_PROJECT}-${UUID.randomUUID().toString()}"
def podtemplate = """
apiVersion: v1
kind: Pod
metadata:
  annotations:
    com.cloudbees.sidecar-injector/inject: no
spec:
  securityContext:
     runAsUser: 0
  imagePullSecrets:
  - name: registrypullsecret
  containers:
  - name: jnlp
    workingDir: /home/jenkins
    volumeMounts:
      - name: ca-bundles
        mountPath: /etc/pki/ca-trust/extracted/pem/tls-ca-bundle.pem
        subPath: ca-certificates.crt
      - name: ca-bundles
        mountPath: /etc/pki/java/cacerts
        subPath: cacerts
  - name: sonar-scanner
    image: artifactory.globaldevtools.bbva.com:443/hub.docker.com-remote/sonarsource/sonar-scanner-cli:11.1.1.1661_6.2.1
    securityContext:
      runAsUser: 0
    command:
    - cat
    tty: true
    resources:
      limits:
        memory: 512Mi
        cpu: 500m
      requests:
        memory: 256Mi
        cpu: 250m
  - name: python-311
    image: artifactory.globaldevtools.bbva.com:443/hub.docker.com-remote/library/python:3.11
    securityContext:
      runAsUser: 0
    command:
    - cat
    tty: true
    resources:
      limits:
        memory: 1Gi
        cpu: 1
      requests:
        memory: 1Gi
        cpu: 1
  - name: aws-cli
    image: artifactory.globaldevtools.bbva.com:443/hub.docker.com-remote/amazon/aws-cli:2.13.2
    securityContext:
      runAsUser: 0
    command:
    - cat
    tty: true
    resources:
      limits:
        memory: 512Mi
        cpu: 250m
      requests:
        memory: 256Mi
        cpu: 250m
  - name: kaniko
    image: artifactory.globaldevtools.bbva.com:443/gcr.io-remote/kaniko-project/executor:v1.23.2-debug
    imagePullPolicy: IfNotPresent
    securityContext:
      runAsUser: 0
    command:
    - /busybox/cat
    tty: true
    volumeMounts:
    - name: ca-bundles
      mountPath: /kaniko/ssl/certs/ca-certificates.crt
      subPath: ca-certificates.crt
    resources:
      limits:
        memory: "2Gi"
        cpu: 2
      requests:
        memory: "2Gi"
        cpu: 2
  - name: gcloud-cli
    image: artifactory.globaldevtools.bbva.com:443/gcr.io-remote/google.com/cloudsdktool/google-cloud-cli:latest
    securityContext:
      runAsUser: 0
    command:
    - cat
    tty: true
    resources:
      limits:
        memory: 1Gi
        cpu: 1
      requests:
        memory: 1Gi
        cpu: 1
  volumes:
  - name: ca-bundles
    configMap:
      defaultMode: 420
      name: ca-bundles
"""

pipeline {
    agent {
        kubernetes {
            label node_label
            defaultContainer 'kaniko'
            yaml podtemplate
        }
    }
    stages {
        stage('Get config file') {
            steps {
                script {
                    def GitBranchIndexingCause = currentBuild.getBuildCauses('jenkins.branch.BranchIndexingCause')
                    if (GitBranchIndexingCause) {
                        currentBuild.result = 'ABORTED'
                        error("Stopping the job because it was triggered by a Git branch indexing cause")
                    }
                    trackStage('Get config file') {
                        configFileProvider(
                            [configFile(fileId: 'ProductConfig', targetLocation: 'product_config.yml')]) {
                        }
                    }
                }
            }
        }
        stage('Read Config YML Files') {
            steps {
                script {
                    trackStage('Read Config YML Files') {
                        def product_config = readYaml file: 'product_config.yml'
                        env.AWS_REGION = product_config.AWS.AWS_REGION
                        env.PRODUCT = product_config.METADATA.PRODUCT.replaceAll("-", "").replaceAll("_", "").toLowerCase()
                        env.UUAA = product_config.METADATA.UUAA
                        env.COUNTRY = product_config.METADATA.COUNTRY
                        env.PROJECT_COUNTRY = product_config.METADATA.COUNTRY.toString()
                        env.SAMUEL_OWNERS = product_config.SAMUEL.OWNERS.toString()
                        def component_config = readYaml file: 'component_config.yml'
                        env.APPLICATION = component_config.APPLICATION.replaceAll("-", "").replaceAll("_", "").toLowerCase()
                        env.SERVICE = component_config.SERVICE
                        env.NAME = component_config.NAME.replaceAll("-", "").replaceAll("_", "").toLowerCase()
                        env.TYPE = component_config.TYPE.toLowerCase()
                        env.COMPONENT = "${TYPE}-${NAME}"
                        env.SCAFFOLD = component_config.SCAFFOLD
                        env.AWS_SERVICE_NAME = "${APPLICATION}-${COMPONENT}"
                        def regionParts = env.AWS_REGION.toLowerCase().split('-')
                        env.AWS_REGION_PREFIX = regionParts[0]
                        env.IMAGE_REPOSITORY_NAME = "genai/${PRODUCT}/${APPLICATION}/${COMPONENT}"
                        def git_url = env.GIT_URL
                        git_url_parts = git_url.split('/')
                        env.PROJECT_KEY = git_url_parts[3]
                        env.REPO_NAME = git_url_parts[4].replaceAll(/\.git$/, '')
                    }
                }
            }
        }
        stage('Selection') {
            steps {
                script {
                    trackStage('Selection') {
                        def GitPushCause = currentBuild.getBuildCauses('jenkins.branch.BranchEventCause')
                        def UserCause = currentBuild.getBuildCauses('hudson.model.Cause$UserIdCause')
                        if (GitPushCause) {
                            env.JOB_RUN = 'Build & Push Docker Image'
                        } else if (UserCause) {
                            switch ("${SERVICE.replaceAll("\\s+", "").toLowerCase()}") {
                                case "apprunner":
                                    DEPLOY = "Deploy App Runner Service"
                                    break
                                case "lambda":
                                    DEPLOY = "Deploy AWS Lambda"
                                    break
                            }
                            timeout(time:120, unit:'SECONDS') {
                                env.JOB_RUN = input(message: 'Select the option to execute:', parameters: [choice(name: 'JOB_RUN', choices: ["${DEPLOY}", 'Build & Push Docker Image'], description: 'Select the job to run')])
                            }
                        }
                    }
                }
            }
        }
        stage('Start') {
            steps {
                script {
                    trackStage('Start') {
                        try {
                            echo "Start flow on branch ${env.BRANCH_NAME}"
                            checkIfPR()
                            setEnvironmentVariables()
                            getVersion()
                            setECRConf(IMAGE_REPOSITORY_NAME, version)
                        } catch (exception) {
                            echo "An exception occurred"
                            print exception
                            throw exception
                        } finally {
                            echo 'We have reached the end of the pipeline.'
                        }
                    }
                }
            }
        }
        stage("AWS Assume Role") {
            steps {
                script {
                    trackStage('AWS Assume Role') {
                        // Assume the Jenkins role in the target account
                        AWS_ASSUME_ROLE = "arn:aws:iam::${env.AWS_ACCOUNT_ID}:role/${AWS_JENKINS_ROLE_NAME}"
                        JENKINS_CREDENTIAL_ID_AWS_ROLE_EXTERNAL_ID = 'AWSRoleExternalId' + env.ENVIRONMENT.capitalize()
                        switch (AWS_REGION_PREFIX) {
                            case 'us':
                                withProxyCredentials {
                                    awsAssumeRole(AWS_ASSUME_ROLE, "Jenkins", JENKINS_CREDENTIAL_ID_AWS_ROLE_EXTERNAL_ID)
                                }
                                break
                            case 'eu':
                                awsAssumeRole(AWS_ASSUME_ROLE, "Jenkins", JENKINS_CREDENTIAL_ID_AWS_ROLE_EXTERNAL_ID)
                                break
                            default:
                                error("Unsupported region prefix: ${AWS_REGION_PREFIX}")
                        }
                    }
                }
            }
        }
        stage('Lint') {
            when {
                expression {
                    return env.JOB_RUN == 'Build & Push Docker Image'
                }
            }
            steps {
                script {
                    trackStage('Lint') {
                        // Ratcheted ruff + mypy (see Makefile `lint`,
                        // ruff.toml, mypy.ini, .lint-baseline.json). Versions
                        // must match deploy/requirements/pyproject.toml: the
                        // baseline is only comparable for the same versions.
                        container('python-311') {
                            sh '''
                                pip install --quiet ruff==0.8.4 mypy==1.13.0
                                make lint
                            '''
                        }
                    }
                }
            }
        }
        stage('Architecture') {
            when {
                expression {
                    return env.JOB_RUN == 'Build & Push Docker Image'
                }
            }
            steps {
                script {
                    trackStage('Architecture') {
                        // AST fitness tests (tests/test_architecture/, see
                        // Makefile `test-architecture`). They import the API
                        // app and the worker factories, so the API project's
                        // dependencies must be installed.
                        withEnvArtifactoryCredentials {
                            container('python-311') {
                                sh '''
                                    make download-poetry
                                    poetry -C deploy/requirements install --no-root --no-interaction
                                    . "$(poetry -C deploy/requirements env info --path)/bin/activate"
                                    pip install --quiet pytest
                                    make test-architecture
                                '''
                            }
                        }
                    }
                }
            }
        }
        stage("Code Test") {
            when {
                expression {
                    return env.JOB_RUN == 'Build & Push Docker Image'
                }
            }
            steps {
                script {
                    trackStage('Code Test') {
                        withEnvArtifactoryCredentials {
                            codeTest()
                        }
                    }
                }
            }
        }
        stage('Send to Sonar') {
            when {
                expression {
                    return env.JOB_RUN == 'Build & Push Docker Image'
                }
            }
            steps {
                script {
                    trackStage('Send to Sonar') {
                        sendToSonar()
                    }
                }
            }
        }
        stage("Samuel pre-build") {
            when {
                expression {
                    return env.JOB_RUN == 'Build & Push Docker Image'
                }
            }
           steps {
                script {
                    trackStage('Samuel pre-build') {
                        withEnvSamuelCredentials {
                            samuelForCodeReview()
                        }
                    }
                }
           }
        }
        stage('Build & Push Docker Image') {
            when {
                expression {
                    return env.JOB_RUN == 'Build & Push Docker Image'
                }
            }
            steps {
                script {
                    trackStage('Build & Push Docker Image') {
                        switch (AWS_REGION_PREFIX) {
                            case 'us':
                                withProxyCredentials {
                                    buildAndPushDockerImage()
                                }
                                break
                            case 'eu':
                                buildAndPushDockerImage()
                                break
                            default:
                                error("Unsupported region prefix: ${AWS_REGION_PREFIX}")
                        }
                    }
                }
            }
        }
        stage ('Deploy service') {
            when {
                expression {
                    return env.JOB_RUN != 'Build & Push Docker Image'
                }
            }
            steps {
                script {
                    trackStage('Deploy service') {
                        switch (AWS_REGION_PREFIX) {
                            case 'us':
                                withProxyCredentials {
                                    deployService()
                                }
                                break
                            case 'eu':
                                deployService()
                                break
                            default:
                                error("Unsupported region prefix: ${AWS_REGION_PREFIX}")
                        }
                    }
                }
            }
        }
    }
    post {
        always {
            catchError(buildResult: 'SUCCESS', stageResult: 'SUCCESS') {
                pipelineFinalize()
            }
            cleanWs()
        }
        changed {
            echo "There have been some changes from the last build"
        }
        success {
            echo "Build successful"
        }
        failure {
            echo "There have been some errors"
        }
        unstable {
            echo "Unstable"
        }
        aborted {
            echo "Aborted"
        }
    }
}

def setEnvironmentVariables() {
    // Set the environment variables based on the branch name
    switch (env.CODE_BRANCH_NAME) {
        case ~/^release\/.+$/:
        case ~/master$/:
            env.ENVIRONMENT = 'live'
            break
        case ~/develop$/:
            env.ENVIRONMENT = 'work'
            break
        case ~/^hotfix\/.+$/:
        case ~/^feature\/.+$/:
            env.ENVIRONMENT = 'dev'
            break
    }
    def product_config = readYaml file: 'product_config.yml'
    product_config.AWS.each { key, value ->
        if (key.startsWith("AWS_ACCOUNT_ID_") && key.endsWith("_${env.ENVIRONMENT.toUpperCase()}")) {
            env.AWS_ACCOUNT_ID = value
        }
    }
}

def buildAndPushDockerImage() {
    // Build and push the Docker image
    if (env.ENVIRONMENT == 'work' || env.ENVIRONMENT == 'live') {
        ARTIFACTORY_DESTINATION = "${ARTIFACTORY_ENDPOINT}/${env.ENVIRONMENT == 'work' ? ARTIFACTORY_DEV_REPOSITORY : ARTIFACTORY_REPOSITORY}/${IMAGE_REPOSITORY_NAME}:${version}"
        buildAndPushDockerEcrArtifactory(JENKINS_CREDENTIAL_ID_BOT_ARTIFACTORY, "${env.WORKSPACE}/", AWS_ECR_REGISTRY, AWS_ECR_DESTINATION, ARTIFACTORY_DESTINATION)
    } else {
        buildAndPushDockerEcrArtifactory(JENKINS_CREDENTIAL_ID_BOT_ARTIFACTORY, "${env.WORKSPACE}/", AWS_ECR_REGISTRY, AWS_ECR_DESTINATION)
    }
}

def deployService() {
    // Deploy the service based on the type of service (Lambda or AppRunner)
    if (env.JOB_RUN == 'Deploy AWS Lambda') {
        deployLambdaFunction(AWS_SERVICE_NAME, AWS_ECR_DESTINATION)
    } else if (env.JOB_RUN == 'Deploy App Runner Service') {
        deployAppRunnerService(AWS_SERVICE_NAME, AWS_ECR_DESTINATION)
    }
}