import boto3
import time
import subprocess

# ---------------------------------------------------------------------------
# Dependencias de entorno: credenciales AWS configuradas (ej: con aws configure) y Docker instalado y corriendo localmente (para build/push de imágenes).
# Instalación de las dependencias necesarias en un bastion Amazon Linux 2023 (EC2):
#   sudo dnf install -y python3-pip docker
#   pip3 install boto3
#   sudo systemctl start docker
#   sudo systemctl enable docker
#   sudo chmod 666 /var/run/docker.sock
# o en unico comando:
#   sudo dnf install -y python3-pip docker && pip3 install boto3 && sudo systemctl start docker && sudo systemctl enable docker && sudo chmod 666 /var/run/docker.sock
# IMPORTANTE: tener al mismo nivel del script las carpetas "api" y "swagger" con sus respectivos Dockerfiles y código.
# PUEDE OBTENER MAS INFORMACION SOBRE EL DESPLIEGUE EN LOS DOCUMENTOS DE LA CARPETA /docs DE ESTE REPOSITORIO.
# ---------------------------------------------------------------------------

REGION = "us-east-1"

ec2   = boto3.client("ec2",   region_name=REGION) # redes
ecs   = boto3.client("ecs",   region_name=REGION) # conetendores
elbv2 = boto3.client("elbv2", region_name=REGION) # balanceador de carga
sts   = boto3.client("sts") # servicio de seguridad para obtener el ID de cuenta y construir la URL del repositorio ECR

ACCOUNT  = sts.get_caller_identity()["Account"]
ECR_ROOT = f"{ACCOUNT}.dkr.ecr.{REGION}.amazonaws.com"

# Tag usado en todos los recursos para poder identificarlos fácilmente y borrarlos luego con el script de teardown.
TAGS     = [{"Key": "Stack", "Value": "arch1"}] # etiqueta para recursos generales
TAGS_ECS = [{"key": "Stack", "value": "arch1"}] # etiqueta para ECS (usa lowercase por limitación de ECS)
TAG_SPECS = lambda resource_type: [{"ResourceType": resource_type, "Tags": TAGS}] # función para generar la estructura de tags necesaria en la creación de recursos (ej: VPC, subnets, security groups, etc)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def render_template(template_path, output_path, old_value, new_value):
    with open(template_path, "r", encoding="utf-8") as f:
        content = f.read()
    content = content.replace(old_value, new_value)
    content = content.replace("\r\n", "\n")
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(content)

def ecr_login():
    print("Login ECR")
    subprocess.run(
        f"aws ecr get-login-password --region {REGION} "
        f"| docker login --username AWS --password-stdin {ECR_ROOT}",
        shell=True, check=True
    )

def build_push_postgres():
    repo = f"{ECR_ROOT}/gamestore-postgres:latest"
    print("Build/push postgres")
    subprocess.run("docker pull postgres:15", shell=True, check=True)
    subprocess.run(f"docker tag postgres:15 {repo}", shell=True, check=True)
    subprocess.run(f"docker push {repo}", shell=True, check=True)

def build_push_api():
    repo = f"{ECR_ROOT}/gamestore-api:latest"
    print("Build/push API")
    subprocess.run("docker build -t gamestore-api ./api", shell=True, check=True)
    subprocess.run(f"docker tag gamestore-api:latest {repo}", shell=True, check=True)
    subprocess.run(f"docker push {repo}", shell=True, check=True)

def build_push_swagger():
    repo = f"{ECR_ROOT}/gamestore-swagger:latest"
    print("Build/push Swagger")
    subprocess.run("docker build -t gamestore-swagger ./swagger", shell=True, check=True)
    subprocess.run(f"docker tag gamestore-swagger:latest {repo}", shell=True, check=True)
    subprocess.run(f"docker push {repo}", shell=True, check=True)

def wait_for_task_running(cluster, service):
    print(f"Esperando que el task '{service}' este RUNNING...")
    while True:
        task_arns = ecs.list_tasks(cluster=cluster, serviceName=service)["taskArns"]
        if task_arns:
            task = ecs.describe_tasks(cluster=cluster, tasks=task_arns)["tasks"][0]
            status = task["lastStatus"]
            print(f"  Estado actual: {status}")
            if status == "RUNNING":
                return task
        time.sleep(10)

def get_task_private_ip(task):
    eni_id = next(
        d["value"]
        for d in task["attachments"][0]["details"]
        if d["name"] == "networkInterfaceId"
    )
    eni_desc = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    return eni_desc["NetworkInterfaces"][0]["PrivateIpAddress"]

def get_task_public_ip(task):
    eni_id = next(
        d["value"]
        for d in task["attachments"][0]["details"]
        if d["name"] == "networkInterfaceId"
    )
    eni_desc = ec2.describe_network_interfaces(NetworkInterfaceIds=[eni_id])
    return eni_desc["NetworkInterfaces"][0]["Association"]["PublicIp"]


# ===========================================================================
# 1. ECR - repositorios e imágenes base
# ===========================================================================

ecr = boto3.client("ecr", region_name=REGION)

for repo_name in ["gamestore-postgres", "gamestore-api", "gamestore-swagger"]:
    try:
        ecr.create_repository(
            repositoryName=repo_name,
            tags=TAGS
        )
        print(f"Repositorio creado: {repo_name}")
    except ecr.exceptions.RepositoryAlreadyExistsException:
        print(f"Repositorio ya existe: {repo_name}")

ecr_login()
build_push_postgres()


# ===========================================================================
# 2. Red: VPC, subnets, IGW, routing
# ===========================================================================

print("\nCreando VPC")
vpc_id = ec2.create_vpc(
    CidrBlock="11.0.0.0/16",
    TagSpecifications=TAG_SPECS("vpc")
)["Vpc"]["VpcId"]
ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsHostnames={"Value": True})
ec2.modify_vpc_attribute(VpcId=vpc_id, EnableDnsSupport={"Value": True})
print("VPC:", vpc_id)

print("Creando subnets")

azs = ec2.describe_availability_zones(
    Filters=[{"Name": "state", "Values": ["available"]}]
)["AvailabilityZones"]

az1 = azs[0]["ZoneName"]
az2 = azs[1]["ZoneName"]

public_subnet = ec2.create_subnet(
    VpcId=vpc_id, CidrBlock="11.0.1.0/24", AvailabilityZone=az1,
    TagSpecifications=TAG_SPECS("subnet")
)["Subnet"]["SubnetId"]

public_subnet2 = ec2.create_subnet(
    VpcId=vpc_id, CidrBlock="11.0.3.0/24", AvailabilityZone=az2,
    TagSpecifications=TAG_SPECS("subnet")
)["Subnet"]["SubnetId"]

private_subnet = ec2.create_subnet(
    VpcId=vpc_id, CidrBlock="11.0.2.0/24", AvailabilityZone=az1,
    TagSpecifications=TAG_SPECS("subnet")
)["Subnet"]["SubnetId"]

print(f"  public_subnet  -> {az1}")
print(f"  public_subnet2 -> {az2}")
print(f"  private_subnet -> {az1}")

print("Creando IGW")
igw = ec2.create_internet_gateway(
    TagSpecifications=TAG_SPECS("internet-gateway")
)["InternetGateway"]["InternetGatewayId"]
ec2.attach_internet_gateway(InternetGatewayId=igw, VpcId=vpc_id)

print("Routing público")
rt_public = ec2.create_route_table(
    VpcId=vpc_id,
    TagSpecifications=TAG_SPECS("route-table")
)["RouteTable"]["RouteTableId"]
ec2.create_route(RouteTableId=rt_public, DestinationCidrBlock="0.0.0.0/0", GatewayId=igw)
ec2.associate_route_table(SubnetId=public_subnet,  RouteTableId=rt_public)
ec2.associate_route_table(SubnetId=public_subnet2, RouteTableId=rt_public)

print("Routing privado")
rt_private = ec2.create_route_table(
    VpcId=vpc_id,
    TagSpecifications=TAG_SPECS("route-table")
)["RouteTable"]["RouteTableId"]
ec2.associate_route_table(SubnetId=private_subnet, RouteTableId=rt_private)


# ===========================================================================
# 3. Security groups
# ===========================================================================

print("Creando security groups")

def make_sg(name, desc):
    return ec2.create_security_group(
        GroupName=name,
        Description=desc,
        VpcId=vpc_id,
        TagSpecifications=TAG_SPECS("security-group")
    )["GroupId"]

swagger_sg  = make_sg("swagger-sg", "swagger")
backend_sg  = make_sg("backend-sg", "backend")
alb_sg      = make_sg("alb-sg", "alb")
endpoint_sg = make_sg("endpoint-sg", "endpoint")

ec2.authorize_security_group_ingress(GroupId=swagger_sg, IpPermissions=[{
    "IpProtocol": "tcp", "FromPort": 8080, "ToPort": 8080,
    "IpRanges": [{"CidrIp": "0.0.0.0/0"}]
}])

ec2.authorize_security_group_ingress(GroupId=alb_sg, IpPermissions=[{
    "IpProtocol": "tcp", "FromPort": 80, "ToPort": 80,
    "IpRanges": [{"CidrIp": "0.0.0.0/0"}]
}])

ec2.authorize_security_group_ingress(GroupId=backend_sg, IpPermissions=[
    {"IpProtocol": "tcp", "FromPort": 5000, "ToPort": 5000,
     "UserIdGroupPairs": [{"GroupId": alb_sg}]},
    {"IpProtocol": "tcp", "FromPort": 5432, "ToPort": 5432,
     "UserIdGroupPairs": [{"GroupId": backend_sg}]}
])

ec2.authorize_security_group_ingress(GroupId=endpoint_sg, IpPermissions=[{
    "IpProtocol": "tcp", "FromPort": 443, "ToPort": 443,
    "UserIdGroupPairs": [
        {"GroupId": backend_sg},
        {"GroupId": swagger_sg}
    ]
}])


# ===========================================================================
# 4. VPC Endpoints
# Los endpoints se taguean con create_tags tras crearlos porque su API
# no acepta TagSpecifications de forma consistente en todas las versiones
# ===========================================================================

print("Creando VPC endpoints")

def create_tagged_endpoint(**kwargs):
    ep_id = ec2.create_vpc_endpoint(**kwargs)["VpcEndpoint"]["VpcEndpointId"]
    ec2.create_tags(Resources=[ep_id], Tags=TAGS)
    return ep_id

create_tagged_endpoint(
    VpcId=vpc_id,
    ServiceName=f"com.amazonaws.{REGION}.s3",
    VpcEndpointType="Gateway",
    RouteTableIds=[rt_private]
)

create_tagged_endpoint(
    VpcId=vpc_id,
    ServiceName=f"com.amazonaws.{REGION}.ecr.api",
    VpcEndpointType="Interface",
    SubnetIds=[private_subnet],
    SecurityGroupIds=[endpoint_sg],
    PrivateDnsEnabled=True
)

create_tagged_endpoint(
    VpcId=vpc_id,
    ServiceName=f"com.amazonaws.{REGION}.ecr.dkr",
    VpcEndpointType="Interface",
    SubnetIds=[private_subnet],
    SecurityGroupIds=[endpoint_sg],
    PrivateDnsEnabled=True
)

create_tagged_endpoint(
    VpcId=vpc_id,
    ServiceName=f"com.amazonaws.{REGION}.logs",
    VpcEndpointType="Interface",
    SubnetIds=[private_subnet],
    SecurityGroupIds=[endpoint_sg],
    PrivateDnsEnabled=True
)


# ===========================================================================
# 4.5 IAM - execution role (usando LabRole del entorno de laboratorio)
# ===========================================================================

iam = boto3.client("iam")
execution_role_arn = iam.get_role(RoleName="LabRole")["Role"]["Arn"]
print("Usando execution role:", execution_role_arn)


# ===========================================================================
# 5. Cluster ECS + servicio Postgres
# ===========================================================================

print("Creando cluster ECS")
ecs.create_cluster(
    clusterName="gamestore-cluster",
    tags=TAGS_ECS
)

print("Registrando task postgres")
ecs.register_task_definition(
    family="postgres",
    executionRoleArn=execution_role_arn,
    networkMode="awsvpc",
    requiresCompatibilities=["FARGATE"],
    cpu="256", memory="512",
    tags=TAGS_ECS,
    containerDefinitions=[{
        "name": "postgres",
        "image": f"{ECR_ROOT}/gamestore-postgres:latest",
        "portMappings": [{"containerPort": 5432}],
        "environment": [
            {"name": "POSTGRES_DB", "value": "gamestore"},
            {"name": "POSTGRES_USER", "value": "gamestore"},
            {"name": "POSTGRES_PASSWORD", "value": "gamestorepass"}
        ]
    }]
)

print("Creando servicio postgres")
ecs.create_service(
    cluster="gamestore-cluster",
    serviceName="postgres",
    taskDefinition="postgres",
    desiredCount=1,
    launchType="FARGATE",
    tags=TAGS_ECS,
    networkConfiguration={"awsvpcConfiguration": {
        "subnets": [private_subnet],
        "securityGroups": [backend_sg],
        "assignPublicIp": "DISABLED"
    }}
)

postgres_task = wait_for_task_running("gamestore-cluster", "postgres")
postgres_ip   = get_task_private_ip(postgres_task)
print("IP privada postgres:", postgres_ip)


# ===========================================================================
# 6. Build API
# ===========================================================================

render_template(
    "api/wait-for-db.sh.template",
    "api/wait-for-db.sh",
    "POSTGRES_IP",
    postgres_ip
)

build_push_api()

print("Registrando task API")
ecs.register_task_definition(
    family="api",
    executionRoleArn=execution_role_arn,
    networkMode="awsvpc",
    requiresCompatibilities=["FARGATE"],
    cpu="256", memory="512",
    tags=TAGS_ECS,
    containerDefinitions=[{
        "name": "api",
        "image": f"{ECR_ROOT}/gamestore-api:latest",
        "portMappings": [{"containerPort": 5000}],
        "environment": [{
            "name":  "DATABASE_URI",
            "value": f"postgresql://gamestore:gamestorepass@{postgres_ip}:5432/gamestore"
        }]
    }]
)


# ===========================================================================
# 7. ALB + servicio API
# ===========================================================================

print("Creando ALB")
alb_resp = elbv2.create_load_balancer(
    Name="api-alb",
    Subnets=[public_subnet, public_subnet2],
    SecurityGroups=[alb_sg],
    Scheme="internet-facing",
    Type="application",
    IpAddressType="ipv4",
    Tags=TAGS
)
alb_arn = alb_resp["LoadBalancers"][0]["LoadBalancerArn"]
alb_dns = alb_resp["LoadBalancers"][0]["DNSName"]
print("ALB DNS:", alb_dns)

tg_arn = elbv2.create_target_group(
    Name="api-target",
    Protocol="HTTP",
    Port=5000,
    VpcId=vpc_id,
    TargetType="ip",
    HealthCheckPath="/api/game",
    Tags=TAGS
)["TargetGroups"][0]["TargetGroupArn"]

elbv2.create_listener(
    LoadBalancerArn=alb_arn,
    Protocol="HTTP", Port=80,
    DefaultActions=[{"Type": "forward", "TargetGroupArn": tg_arn}],
    Tags=TAGS
)

print("Creando servicio API")
ecs.create_service(
    cluster="gamestore-cluster",
    serviceName="api",
    taskDefinition="api",
    desiredCount=1,
    launchType="FARGATE",
    tags=TAGS_ECS,
    loadBalancers=[{
        "targetGroupArn": tg_arn,
        "containerName": "api",
        "containerPort": 5000
    }],
    networkConfiguration={"awsvpcConfiguration": {
        "subnets": [private_subnet],
        "securityGroups": [backend_sg],
        "assignPublicIp": "DISABLED"
    }}
)

ecs.update_service(
    cluster="gamestore-cluster",
    service="api",
    forceNewDeployment=True
)


# ===========================================================================
# 8. Build Swagger
# ===========================================================================

render_template(
    "swagger/swagger-config.json.template",
    "swagger/swagger-config.json",
    "ALB_URL",
    f"http://{alb_dns}/api"
)

build_push_swagger()

print("Registrando task Swagger")
ecs.register_task_definition(
    family="swagger",
    executionRoleArn=execution_role_arn,
    networkMode="awsvpc",
    requiresCompatibilities=["FARGATE"],
    cpu="256", memory="512",
    tags=TAGS_ECS,
    containerDefinitions=[{
        "name": "swagger",
        "image": f"{ECR_ROOT}/gamestore-swagger:latest",
        "portMappings": [{"containerPort": 8080}]
    }]
)

print("Creando servicio Swagger")
ecs.create_service(
    cluster="gamestore-cluster",
    serviceName="swagger",
    taskDefinition="swagger",
    desiredCount=1,
    launchType="FARGATE",
    tags=TAGS_ECS,
    networkConfiguration={"awsvpcConfiguration": {
        "subnets": [public_subnet],
        "securityGroups": [swagger_sg],
        "assignPublicIp": "ENABLED"
    }}
)

ecs.update_service(
    cluster="gamestore-cluster",
    service="swagger",
    forceNewDeployment=True
)


# ===========================================================================
# Resumen final del despliegue
# ===========================================================================

swagger_task   = wait_for_task_running("gamestore-cluster", "swagger")
swagger_pub_ip = get_task_public_ip(swagger_task)

print("\n=== DESPLIEGUE TERMINADO ===")
print(f"API:     http://{alb_dns}/api/[operation] (ej: http://{alb_dns}/api/game)")
print(f"Swagger: http://{swagger_pub_ip}:8080")