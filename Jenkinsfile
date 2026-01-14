pipeline {
  agent any

  environment {
    IMAGE_NAME = "ansible-control:local"
    SSH_DIR    = "/opt/ansible_docker_ssh"
    PROJECT_DIR = "/home/ansible/PROJECT_ANSIBLE"
    INVENTORY  = "inventories/prod/hosts.yml"
    PLAYBOOK   = "playbooks/site.yml"
  }

  stages {

    stage('Build Ansible Image') {
      steps {
        dir("${PROJECT_DIR}") {
          sh 'docker build -t ${IMAGE_NAME} .'
        }
      }
    }

    stage('Syntax Check') {
      steps {
        dir("${PROJECT_DIR}") {
          sh '''
            docker run --rm \
              -v ${SSH_DIR}:/root/.ssh:ro \
              ${IMAGE_NAME} \
              ansible-playbook -i ${INVENTORY} ${PLAYBOOK} --syntax-check
          '''
        }
      }
    }

    stage('Dry Run (ai_worker)') {
      steps {
        dir("${PROJECT_DIR}") {
          sh '''
            docker run --rm \
              -v ${SSH_DIR}:/root/.ssh:ro \
              ${IMAGE_NAME} \
              ansible-playbook \
                -i ${INVENTORY} \
                ${PLAYBOOK} \
                --check --diff -l ai_worker
          '''
        }
      }
    }

    stage('🚨 Approve Deploy') {
      steps {
        input message: '''
Dry Run이 정상적으로 끝났습니다.

👉 실제 배포를 진행하시겠습니까?
(승인 시 운영 서버에 즉시 반영됩니다)
'''
      }
    }
  }
}
