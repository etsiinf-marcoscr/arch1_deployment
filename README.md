### TFG de Monitorización y Análisis de Arquitecturas Cloud basadas en Contenedores   
#### **Autor: Marcos Casado Ruiz**

## Despliegue básico mediante bastión de despliegue (EC2)

_Pueden encontrarse instrucciones detalladas para el despliegue de la máquina virtual EC2 que actua como bastión en la carpeta ```docs``` o pinchando el siguiente enlace: [Documento de despliegue del bastión](docs/bastion-deployment.md)._

Paso 1: Instalar git y clonar el repositorio en un bastion Amazon Linux 2023 (EC2):
```bash
   sudo dnf install git -y
   git clone https://github.com/etsiinf-marcoscr/arch1_deployment.git
```

Paso 2: Instalar las dependencias necesarias en el bastion:
```bash
   sudo dnf install -y python3-pip docker && pip3 install boto3 && sudo systemctl start docker && sudo systemctl enable docker && sudo chmod 666 /var/run/docker.sock
```

Paso 3: Configurar las credenciales AWS (también puede usarse en muchos casos ```aws login```):
```bash
   aws configure
```

Paso 4: Abrir la carpeta del repo y ejecutar el script de despliegue:
```bash
   cd arch1_deployment/
   python3 arch1-deployment.py
```

Paso 5 (_opcional_): Borrado de los recursos creados por el script de despliegue (para evitar costes innecesarios):
```bash
   python3 arch1-teardown.py
```
Recuerde que en caso de haber utilizado una máquina EC2 como bastión para el despliegue, es necesario eliminarla manualmente para evitar costes innecesarios.   
_Puede encontrar más información en la carpeta ```docs``` o pinchando el siguiente enlace: [Documento de borrado del bastión](docs/bastion-teardown.md)._